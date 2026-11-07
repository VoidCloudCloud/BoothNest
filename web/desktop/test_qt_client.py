# SPDX-License-Identifier: GPL-3.0-only
"""Native event ordering and shutdown regression tests. Requires requirements-qt.txt."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import ast
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qtclient.core import Backend
from qtclient.window import Window
from qtclient.dialogs import Detail
from qtclient.discovery import QuickFind, public_state, share_text, import_filter
from qtclient.presentation import appearance, tr, EN


class FakeBackend(QObject):
    ready = Signal(str,str)
    failed = Signal(str)
    stopped = Signal()

    def __init__(self, home):
        super().__init__()
        self.home, self.stops = Path(home), 0

    def stop(self):
        self.stops += 1
        self.stopped.emit()


def results(item_id):
    return {'items':[{'id':item_id,'title':str(item_id),'author':'test','media':[],'priceKnown':True,'price':0}],
            'facets':{},'page':1,'totalPages':1,'count':1,'totalRecords':1,'elapsedMs':1}


class QtClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        appearance.apply({'language':'zh','currency':'JPY','theme':'charcoal'})
        self.directory = tempfile.TemporaryDirectory()
        self.backend = FakeBackend(self.directory.name)
        self.window = Window(self.backend)

    def tearDown(self):
        self.window.preference_busy = False
        self.window.preference_queue.clear()
        self.window.close()
        self.app.processEvents()
        self.directory.cleanup()

    def test_late_search_response_cannot_replace_new_results(self):
        pending = []
        self.window.api.request = lambda path, done=None, **kw: pending.append((path,done,kw))
        self.window.connected = True
        self.window.state['q'] = 'old'
        self.window.load()
        self.window.state['q'] = 'new'
        self.window.load()
        pending[1][1](results(2))
        pending[0][1](results(1))
        self.assertEqual(self.window.item_model.items[0]['id'], 2)
        pending[0][2]['error']('obsolete network error')
        self.assertTrue(self.window.error_label.isHidden())

    def test_close_waits_for_preferences_before_stopping_backend(self):
        self.window.show()
        self.window.preference_busy = True
        self.window.close()
        self.assertEqual(self.backend.stops, 0)
        self.window.preference_busy = False
        QTest.qWait(220)
        self.assertEqual(self.backend.stops, 1)
        self.assertTrue(self.window.ready_to_close)

    def test_shutdown_ignores_late_result(self):
        pending = []
        self.window.api.request = lambda path, done=None, **kw: pending.append(done)
        self.window.connected = True
        self.window.load()
        self.window.shutting_down = True
        pending[0](results(3))
        self.assertEqual(self.window.item_model.rowCount(), 0)

    def test_external_service_must_be_loopback(self):
        backend = Backend(Path(__file__).resolve().parents[1], self.directory.name, url='https://booth.pm')
        errors = []
        backend.failed.connect(errors.append)
        backend.start()
        self.assertEqual(len(errors), 1)
        self.assertIsNone(backend.process)

    def test_all_native_translation_keys_have_english(self):
        missing = set()
        for path in (Path(__file__).parent / 'qtclient').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text('utf-8'))):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id == 'tr' and node.args and isinstance(node.args[0],ast.Constant):
                    key = node.args[0].value
                    if key not in EN: missing.add(key)
        self.assertEqual(missing,set())

    def test_live_appearance_preserves_user_data_and_updates_detail(self):
        self.window.api.request = lambda *args,**kwargs: None
        item = dict(results(3)['items'][0], title='原始商品', bio='原始说明', price=1000,
                    translations={'en':{'title':'English item','bio':'English description'}},
                    variations=[{'name':'原始规格','price':1000}])
        panel = Detail(self.window,item)
        self.window.dialogs.append(panel)
        self.window.item_model.replace([item]); self.window.table_model.replace([item])
        self.window.state.update(q='用户的路径与文本',tag=['商品详情'])
        self.window.search.setText('用户的路径与文本')
        self.window.debounce.stop()
        state = deepcopy(self.window.state)
        appearance.apply({'language':'en','currency':'CNY','theme':'cloud'})
        self.assertEqual(panel.title.text(),'English item')
        self.assertEqual(panel.description.toPlainText(),'English description')
        self.assertIn('CNY 48.00',panel.price.text())
        self.assertEqual(panel.variation_model.data(panel.variation_model.index(0,1)),'CNY 48.00')
        self.assertEqual(self.window.table_model.data(self.window.table_model.index(0,0)),'English item')
        self.assertEqual(self.window.table_model.headerData(2,Qt.Orientation.Horizontal),'Price CNY')
        self.assertEqual(self.window.nav_buttons['purchased'].text(),'Purchases')
        self.assertEqual(self.window.state,state)
        self.assertEqual(self.window.search.text(),'用户的路径与文本')
        self.assertEqual(item['variations'][0]['name'],'原始规格')
        self.assertEqual(appearance.money(1000),'CNY 48.00')
        appearance.apply({'currency':'USD'})
        self.assertEqual(appearance.money(1000),'USD 6.70')
        self.assertEqual(appearance.money(0),'Free')
        self.assertEqual(appearance.money(None),'Price unknown')
        appearance.apply({'language':'zh','currency':'JPY','theme':'charcoal'})
        self.assertEqual(panel.title.text(),'原始商品')
        self.assertEqual(panel.description.toPlainText(),'原始说明')
        self.assertEqual(self.window.nav_buttons['purchased'].text(),'已购清单')
        panel.close()

    def test_appearance_saves_serialize_and_preserve_other_preferences(self):
        pending = []
        self.window.api.request = lambda path,done=None,**kwargs: pending.append((done,kwargs))
        self.window.preferences_ready = True
        self.window.change_appearance('language','en')
        self.window.change_appearance('currency','CNY')
        self.window.change_appearance('theme','cloud')
        latest = {'favourites':[77],'saved-searches':[],'other-existing-setting':'untouched','language':'zh','currency':'JPY','theme':'charcoal'}
        while pending:
            done, kwargs = pending.pop(0)
            if 'body' in kwargs:
                latest.update(kwargs['body']); done({'ok':True})
            else:
                done(dict(latest))
        self.assertFalse(self.window.preference_busy)
        self.assertEqual(latest['favourites'],[77])
        self.assertEqual(latest['other-existing-setting'],'untouched')
        self.assertEqual((latest['language'],latest['currency'],latest['theme']),('en','CNY','cloud'))

    def test_appearance_failure_restores_saved_choice(self):
        self.window.preferences_ready = True
        self.window.api.request = lambda path,done=None,**kwargs: kwargs['error']('test save failure')
        self.window.change_appearance('language','en')
        self.assertEqual(appearance.language,'zh')
        self.assertEqual(self.window.language.currentData(),'zh')
        self.assertEqual(self.window.error_label.text(),'test save failure')

    def test_appearance_can_be_selected_before_backend_is_ready(self):
        pending = []
        self.window.api.request = lambda path,done=None,**kwargs: pending.append((done,kwargs))
        self.window.change_appearance('currency','USD')
        self.assertEqual(pending,[])
        self.window.initial_preferences({'currency':'JPY'})
        self.assertEqual(appearance.currency,'USD')
        pending.pop(0)[0]({'currency':'JPY','favourites':[9]})
        done,kwargs = pending.pop(0)
        self.assertEqual(kwargs['body'],{'currency':'USD'})
        done({'ok':True})

    def test_palette_stale_results_keyboard_and_filter_reset(self):
        pending = []
        self.window.connected = True
        self.window.api.request = lambda path,done=None,**kwargs: pending.append((path,done,kwargs))
        panel = QuickFind(self.window)
        self.window.dialogs.append(panel)
        panel.show()
        panel.input.setText('MAYO'); panel.search()
        pending[0][1]({'tags':[{'name':'obsolete','count':1}]})
        self.assertFalse(panel.results)
        pending[1][1]({'avatars':[{'slug':'mayo','en':'MAYO','count':3}],'authors':[{'name':'作者','count':2}],'tags':[{'name':'衣装','count':4}]})
        self.window.state.update(view='purchased',adult='all',purchase='recorded',minBytes=1234)
        QTest.keyClick(panel.input,Qt.Key.Key_Down)
        self.assertEqual(panel.list.currentItem().data(Qt.ItemDataRole.UserRole),('avatars','mayo'))
        QTest.keyClick(panel.input,Qt.Key.Key_Return)
        self.assertEqual(self.window.state['avatar'],['mayo'])
        self.assertEqual(self.window.state['adult'],'all')
        self.assertEqual(self.window.state['view'],'items')
        self.assertNotIn('purchase',self.window.state)
        self.assertNotIn('minBytes',self.window.state)

    def test_palette_defers_requests_during_ime_composition(self):
        pending = []
        self.window.api.request = lambda *args,**kwargs: pending.append(args)
        panel = QuickFind(self.window)
        self.window.dialogs.append(panel)
        panel.show()
        self.app.sendEvent(panel.input,QInputMethodEvent('衣',[]))
        panel.input.setText('衣')
        QTest.qWait(180)
        self.assertEqual(len(pending),1)
        self.assertTrue(panel.composing)
        self.app.sendEvent(panel.input,QInputMethodEvent('',[]))
        QTest.qWait(180)
        self.assertEqual(len(pending),2)
        panel.close()

    def test_share_roundtrip_strips_private_fields_and_paths(self):
        state = {'view':'favourites','sort':'local-size','adult':'all','q':'MAYO * ~',
                 'tag':['衣装','限定'],'excludeTag':['限定'],'author':['作家'],
                 'availability':'local','purchase':'recorded','ids':[17,25],
                 'fileType':['zip'],'localCategory':['private'],'minBytes':123,'duplicates':True,
                 'token':'SECRET','root':r'C:\private','page':4,'pageSize':40,'min':0}
        original = deepcopy(state)
        text = share_text(state)
        self.assertEqual(share_text(import_filter(text)),text)
        self.assertEqual(state,original)
        parsed = import_filter(text)
        self.assertEqual(parsed['view'],'items')
        self.assertEqual(parsed['sort'],'trending')
        for key in ('availability','purchase','ids','fileType','localCategory','minBytes','duplicates','token','root','page'):
            self.assertNotIn(key,parsed)
        self.assertEqual(parsed['tag'],['衣装'])
        self.assertNotIn('SECRET',text)
        self.assertNotIn('q',public_state({'q':r'C:\private\account'}))
        self.assertNotIn('q',public_state({'q':'file:///home/private'}))
        self.assertNotIn('q',public_state({'q':'token=SECRET'}))

    def test_import_web_filter_is_local_parse_and_validated(self):
        state = import_filter('https://example.org/?avatar=mayo&tag=A&tag=B&excludeTag=B&adult=all&token=SECRET&ids=9&view=purchased&min=-1')
        self.assertEqual(state['avatar'],['mayo'])
        self.assertNotIn('token',state)
        self.assertNotIn('ids',state)
        self.assertNotIn('min',state)
        self.assertEqual(state['view'],'items')
        with self.assertRaises(ValueError): import_filter('javascript:alert(1)')
        with self.assertRaises(ValueError): import_filter('?token=SECRET&path=C%3A%5Cprivate')
        with self.assertRaises(ValueError): import_filter('?'+'q=x&'*600)


if __name__ == '__main__':
    unittest.main()

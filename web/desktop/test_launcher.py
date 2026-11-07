# SPDX-License-Identifier: GPL-3.0-only
"""Launcher regressions using temporary homes and an authenticated loopback stub."""
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_lifecycle import BrowserWindowProbe, WindowLifetime, uses_profile
spec = importlib.util.spec_from_file_location('boothnest_launcher', Path(__file__).with_name('main.py'))
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='boothnest-launcher-')
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name) / '中文 library'
        self.home.mkdir()

    def test_shortcut_home_overrides_environment_and_working_directory(self):
        with patch.object(sys, 'argv', ['BoothNest.exe', '--home', str(self.home)]), patch.dict(os.environ, {'BOOTH_NEST_HOME': str(self.home / 'other')}):
            self.assertEqual(launcher.home_dir(), self.home)

    def test_relative_or_missing_home_is_rejected(self):
        for args in [['--home'], ['--home', 'relative']]:
            with patch.object(sys, 'argv', ['BoothNest.exe', *args]), self.assertRaises(ValueError):
                launcher.home_dir()

    def test_installed_executable_remembers_its_data_home(self):
        (self.home / 'data-home.json').write_text(json.dumps({'home': str(self.home / 'saved')}), encoding='utf-8')
        self.assertEqual(launcher.installed_home(self.home), self.home / 'saved')
        (self.home / 'data-home.json').write_text('{"home":"relative"}', encoding='utf-8')
        with self.assertRaises(ValueError):
            launcher.installed_home(self.home)

    def session(self, token='fixture-token'):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                valid = self.path == '/api/desktop/state' and self.headers.get('X-BoothNest-Token') == 'fixture-token'
                self.send_response(200 if valid else 403)
                self.end_headers()
                self.wfile.write(json.dumps({'enabled': valid}).encode())
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        record = {'url': f'http://127.0.0.1:{server.server_port}', 'token': token, 'home': str(self.home)}
        (self.home / 'desktop-session.json').write_text(json.dumps(record), encoding='utf-8')
        return record

    def test_existing_server_is_authenticated_before_reuse(self):
        record = self.session()
        self.assertEqual(launcher.existing_session(self.home), record)

    def test_wrong_token_and_other_home_cannot_be_reused(self):
        self.session('wrong-token')
        self.assertIsNone(launcher.existing_session(self.home))
        record = self.session()
        record['home'] = str(self.home / 'other')
        (self.home / 'desktop-session.json').write_text(json.dumps(record), encoding='utf-8')
        self.assertIsNone(launcher.existing_session(self.home))

    def test_record_cannot_launch_an_external_page(self):
        (self.home / 'desktop-session.json').write_text(json.dumps({'url': 'https://example.invalid', 'token': 'fixture'}), encoding='utf-8')
        self.assertIsNone(launcher.existing_session(self.home))

    def test_reopening_shortcut_restores_window_without_another_server(self):
        record = {'url': 'http://127.0.0.1:4317'}
        lock = Mock()
        lock.acquire.return_value = False
        with patch.object(sys, 'argv', ['BoothNest.exe']), patch.object(launcher, 'home_dir', return_value=self.home), patch('boothlib.instance.InstanceLock', return_value=lock), patch('boothlib.app.find_browser', return_value='edge'), patch.object(launcher, 'existing_session', return_value=record), patch.object(launcher, 'open_window') as window, patch.object(launcher.subprocess, 'Popen') as child, patch.object(launcher, 'message') as message:
            self.assertEqual(launcher.main(), 0)
            self.assertEqual(window.call_args.args[:3], ('edge', record['url'], self.home))
            child.assert_not_called()
            message.assert_not_called()

    def test_open_window_survives_expired_heartbeat_and_close_hint(self):
        for close_hint in [0, 1]:
            with self.subTest(close_hint=close_hint):
                child = Mock()
                child.pid = 12345
                child.poll.side_effect = [None, None, None, 0, 0]
                lock = Mock()
                lock.acquire.return_value = True
                probe = Mock()
                probe.is_open.return_value = True
                state = {'enabled': True, 'lastHeartbeat': 1, 'closeHint': close_hint}
                def response(*args, **kwargs):
                    return io.BytesIO(json.dumps(state).encode())
                with patch.object(sys, 'argv', ['BoothNest.exe']), patch.object(launcher, 'home_dir', return_value=self.home), patch('boothlib.instance.InstanceLock', return_value=lock), patch('boothlib.app.find_browser', return_value='edge'), patch.object(launcher, 'open_window'), patch.object(launcher.subprocess, 'Popen', return_value=child), patch.object(launcher.urllib.request, 'urlopen', side_effect=response), patch.object(launcher.time, 'sleep'), patch.object(launcher, 'BrowserWindowProbe', return_value=probe):
                    self.assertEqual(launcher.main(), 0)
                self.assertEqual(probe.is_open.call_count, 2)
                child.terminate.assert_not_called()


class WindowLifetimeTests(unittest.TestCase):
    def test_profile_matching_is_exact_and_accepts_windows_case_and_spaces(self):
        profile = r'F:\My Library\browser-next'
        self.assertTrue(uses_profile(['edge', '--user-data-dir=f:/my library/browser-next'], profile))
        self.assertTrue(uses_profile(['edge', '--user-data-dir', profile], profile))
        self.assertFalse(uses_profile(['edge', '--user-data-dir=' + profile + '-other'], profile))
        self.assertFalse(uses_profile(['edge'], profile))

    def test_open_window_survives_a_day_without_page_activity(self):
        lifetime = WindowLifetime()
        self.assertFalse(lifetime.should_stop(True, 0))
        self.assertFalse(lifetime.should_stop(True, 86400))

    def test_all_windows_must_remain_closed_for_the_grace_period(self):
        lifetime = WindowLifetime()
        self.assertFalse(lifetime.should_stop(True, 0))
        self.assertFalse(lifetime.should_stop(False, 10))
        self.assertFalse(lifetime.should_stop(False, 14.9))
        self.assertTrue(lifetime.should_stop(False, 15))

    def test_reload_or_another_open_window_cancels_pending_close(self):
        lifetime = WindowLifetime()
        lifetime.should_stop(True, 0)
        lifetime.should_stop(False, 10)
        self.assertFalse(lifetime.should_stop(True, 14))
        self.assertFalse(lifetime.should_stop(False, 20))
        self.assertFalse(lifetime.should_stop(False, 24.9))

    def test_unknown_window_access_does_not_prove_a_close(self):
        lifetime = WindowLifetime()
        lifetime.should_stop(True, 0)
        lifetime.should_stop(False, 10)
        self.assertFalse(lifetime.should_stop(None, 20))
        self.assertFalse(lifetime.should_stop(False, 21))
        self.assertFalse(lifetime.should_stop(False, 25.9))

    def test_unseen_startup_window_does_not_count_as_closed(self):
        lifetime = WindowLifetime()
        self.assertFalse(lifetime.should_stop(False, 0))
        self.assertFalse(lifetime.should_stop(False, 100))

    @unittest.skipUnless(os.name == 'nt', 'Windows native probe')
    def test_unrelated_profile_does_not_adopt_other_browser_windows(self):
        with tempfile.TemporaryDirectory(prefix='boothnest-unrelated-profile-') as folder:
            self.assertIsNot(BrowserWindowProbe(folder).is_open(), True)


if __name__ == '__main__':
    unittest.main(verbosity=2)

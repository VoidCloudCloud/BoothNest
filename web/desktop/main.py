# SPDX-License-Identifier: GPL-3.0-only
"""BoothNest GUI launcher. No interpreter or Node installation is needed in releases."""
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
SOURCE = ROOT / 'site' if getattr(sys, 'frozen', False) else ROOT
sys.path.insert(0, str(SOURCE / 'engine'))
from browser_lifecycle import BrowserWindowProbe, WindowLifetime


def installed_home(folder):
    pointer = folder / 'data-home.json'
    if not pointer.exists():
        return None
    value = json.loads(pointer.read_text(encoding='utf-8'))
    target = value.get('home') if isinstance(value, dict) else None
    if not isinstance(target, str) or not Path(target).is_absolute():
        raise ValueError('安装目录中的 data-home.json 必须指定绝对数据路径')
    return Path(target)


def home_dir():
    override = os.environ.get('BOOTH_NEST_HOME')
    if '--home' in sys.argv:
        index = sys.argv.index('--home')
        if index + 1 >= len(sys.argv):
            raise ValueError('--home 需要一个绝对路径')
        override = sys.argv[index + 1]
    if override and not Path(override).is_absolute():
        raise ValueError('BOOTH_NEST_HOME must be absolute')
    if override:
        return Path(override)
    saved = installed_home(Path(sys.executable).parent) if getattr(sys, 'frozen', False) else None
    return saved or Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'BoothNest'


def existing_session(home):
    """Trust only a live, authenticated loopback service recorded by this home."""
    try:
        record = json.loads((home / 'desktop-session.json').read_text(encoding='utf-8'))
        url = urlsplit(record['url'])
        if url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
            return None
        if record.get('home') and Path(record['home']).resolve() != home.resolve():
            return None
        request = urllib.request.Request(record['url'].rstrip('/') + '/api/desktop/state', headers={'X-BoothNest-Token': record['token']})
        with urllib.request.urlopen(request, timeout=3) as response:
            state = json.load(response)
        return record if isinstance(state, dict) and state.get('enabled') else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def open_window(browser, url, home, log):
    from boothlib.app import _spawn_browser
    profile = home / 'browser-next'
    profile.mkdir(exist_ok=True)
    args = [browser, '--app=' + url, '--user-data-dir=' + str(profile), '--no-first-run', '--no-default-browser-check', '--disable-sync', '--disable-extensions', '--disable-features=Translate,TranslateUI,msEdgeIdentityFeature,EdgeSync,msImplicitSignin', '--window-size=1480,940']
    _spawn_browser(args, log)


def message(title, text):
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, str(text), title, 0x40)


def install():
    if not getattr(sys, 'frozen', False):
        raise RuntimeError('Install from the built Windows package.')
    source = Path(sys.executable).parent.resolve()
    programs = (Path(os.environ['LOCALAPPDATA']) / 'Programs').resolve()
    target = programs / 'BoothNest'
    if target.parent.resolve() != programs or target.name != 'BoothNest':
        raise RuntimeError('Invalid installation target')
    home = home_dir()
    if '--home' not in sys.argv and not os.environ.get('BOOTH_NEST_HOME'):
        home = installed_home(target) or home
    from boothlib.instance import InstanceLock
    lock = InstanceLock(home)
    if not lock.acquire():
        raise RuntimeError('请先关闭正在运行的 BoothNest，再安装更新。')
    try:
        if source != target.resolve():
            if target.exists():
                backup = programs / ('BoothNest-backup-' + time.strftime('%Y%m%d-%H%M%S'))
                if backup.exists():
                    raise RuntimeError('Backup target already exists')
                shutil.copytree(target, backup)
            shutil.copytree(source, target, dirs_exist_ok=True)
        (target / 'data-home.json').write_text(json.dumps({'home': str(home)}, ensure_ascii=False), encoding='utf-8')
        # Standard COM shortcut creation; no PowerShell script or execution-policy change.
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        command = "$s=New-Object -ComObject WScript.Shell; $p=Join-Path ([Environment]::GetFolderPath('Desktop')) 'BoothNest.lnk'; $l=$s.CreateShortcut($p); $l.TargetPath=" + quote(target / 'BoothNest.exe') + "; $l.WorkingDirectory=" + quote(target) + "; $l.Arguments=" + quote(subprocess.list2cmdline(['--home', str(home)])) + "; $l.Save()"
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command], check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        message('BoothNest', '安装完成：\n' + str(target) + '\n\n个人库存与设置保存在独立数据目录。')
    finally:
        lock.release()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        from worker import run
        run(sys.argv[2])
        return 0
    if '--install' in sys.argv:
        install()
        return 0
    from boothlib.instance import InstanceLock
    from boothlib.app import find_browser
    home = home_dir()
    home.mkdir(parents=True, exist_ok=True)
    logs = home / 'logs'
    logs.mkdir(exist_ok=True)
    lock = InstanceLock(home)
    if not lock.acquire():
        record = existing_session(home)
        browser = find_browser()
        if record and browser:
            open_window(browser, record['url'], home, lambda _: None)
        else:
            message('BoothNest', '已有实例正在使用该数据目录，但无法连接。请关闭旧 BoothNest 后重试。\n\n' + str(home))
        return 0
    child = None
    def log(text):
        with (logs / 'desktop.log').open('a', encoding='utf-8') as stream:
            stream.write(time.strftime('%Y-%m-%d %H:%M:%S ') + str(text) + '\n')
    try:
        browser = find_browser()
        if not browser:
            raise RuntimeError('请安装 Microsoft Edge 或 Google Chrome。')
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', 4317))
            except OSError:
                probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        token = secrets.token_hex(32)
        node = ROOT / 'runtime' / 'node.exe' if getattr(sys, 'frozen', False) else Path(os.environ.get('BOOTH_NEST_NODE') or shutil.which('node') or str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'))
        worker = Path(sys.executable).with_name('BoothNestEngine.exe') if getattr(sys, 'frozen', False) else None
        env = {**os.environ, 'BOOTH_NEST_WEB_HOME': str(home / 'web'), 'BOOTH_NEST_ENGINE_HOME': str(home), 'BOOTH_NEST_DESKTOP_TOKEN': token}
        if worker:
            env['BOOTH_NEST_ENGINE_EXE'] = str(worker)
        else:
            env['BOOTH_NEST_PYTHON'] = sys.executable
        with (logs / 'server.log').open('ab', buffering=0) as output:
            child = subprocess.Popen([str(node), str(SOURCE / 'server.mjs'), str(port)], cwd=SOURCE, env=env, stdin=subprocess.PIPE, stdout=output, stderr=output, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            url = f'http://127.0.0.1:{port}'
            def state():
                request = urllib.request.Request(url + '/api/desktop/state', headers={'X-BoothNest-Token': token})
                with urllib.request.urlopen(request, timeout=3) as response:
                    return json.load(response)
            for _ in range(150):
                if child.poll() is not None:
                    raise RuntimeError('本地服务退出，请查看 ' + str(logs / 'server.log'))
                try:
                    state()
                    break
                except Exception:
                    time.sleep(.2)
            else:
                raise RuntimeError('本地服务未能启动。')
            record = {'url': url, 'token': token, 'pid': os.getpid(), 'nodePid': child.pid, 'version': '2.0.0-beta.5', 'home': str(home)}
            (home / 'desktop-session.json').write_text(json.dumps(record), encoding='utf-8')
            open_window(browser, url, home, log)
            log('GUI browser launched at ' + url)
            started = time.monotonic()
            state_failures = 0
            windows = BrowserWindowProbe(home / 'browser-next')
            lifetime = WindowLifetime()
            stale_logged = False
            log('GUI lifecycle: tracking native browser windows; heartbeat pauses do not close the service')
            while child.poll() is None:
                time.sleep(.5)
                window_open = windows.is_open()
                if lifetime.should_stop(window_open, time.monotonic()):
                    log('GUI close confirmed: all application windows closed')
                    break
                try:
                    current = state()
                    state_failures = 0
                except (urllib.error.URLError, OSError):
                    # The HTTP listener closes slightly before Node exits on shutdown.
                    time.sleep(.5)
                    if child.poll() is not None:
                        break
                    state_failures += 1
                    if state_failures >= 6:
                        raise RuntimeError('本地服务无法响应，请查看 ' + str(logs / 'server.log'))
                    continue
                now_ms = time.time() * 1000
                if current['lastHeartbeat']:
                    stale = now_ms - current['lastHeartbeat'] > 120000
                    if stale and not stale_logged:
                        log('GUI heartbeat paused; keeping service until native window closure is confirmed')
                    stale_logged = stale
                elif time.monotonic() - started > 60:
                    raise RuntimeError('窗口未能加载界面，请查看桌面启动日志。')
            # An authenticated shutdown lets scans cancel and public batches commit completed items.
            try:
                req = urllib.request.Request(url + '/api/desktop/shutdown', method='POST', headers={'X-BoothNest-Token': token})
                urllib.request.urlopen(req, timeout=20).close()
            except Exception:
                pass
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.terminate()
            log('GUI service stopped')
        return 0
    finally:
        if child and child.poll() is None:
            child.terminate()
        lock.release()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        if '--worker' in sys.argv:
            if sys.stderr:
                sys.stderr.write(traceback.format_exc())
            raise SystemExit(1)
        try:
            home = home_dir()
        except (OSError, ValueError):
            home = Path(os.environ.get('TEMP', str(Path.home()))) / 'BoothNest'
        (home / 'logs').mkdir(parents=True, exist_ok=True)
        (home / 'logs' / 'crash.log').write_text(traceback.format_exc(), encoding='utf-8')
        message('BoothNest 启动失败', traceback.format_exc().splitlines()[-1] + '\n\n' + str(home / 'logs' / 'crash.log'))
        raise SystemExit(1)

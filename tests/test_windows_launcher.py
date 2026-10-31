"""Launcher checks use fake application files and temporary shared data, never the ledger."""
import asyncio
import io
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import windows_launcher as launcher


class WindowsLauncherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.program = self.root / 'program'
        for relative, content in [('backend/__init__.py', ''), ('backend/db.py', '# fake database module'),
                                  ('backend/main.py', '''import asyncio
async def app(scope, receive, send):
 if scope['type']=='lifespan':
  while True:
   message=await receive()
   if message['type']=='lifespan.startup':
    await asyncio.sleep(0.2)
    await send({'type':'lifespan.startup.complete'})
   elif message['type']=='lifespan.shutdown':
    await send({'type':'lifespan.shutdown.complete'})
    return
 else:
  await send({'type':'http.response.start','status':200,'headers':[(b'content-type',b'application/json')]})
  await send({'type':'http.response.body','body':b'{"ok":true}'})
'''), ('frontend/dist/index.html', '<script src="/assets/app.js"></script>'),
                                  ('frontend/dist/assets/app.js', '// fixture')]:
            target = self.program / relative; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')
        self.env = patch.dict(os.environ)
        self.env.start(); self.addCleanup(self.env.stop)
        self.data = launcher.configure_data_paths(self.root / 'ProgramData')

    @staticmethod
    def free_port():
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]

    def test_shared_paths_replace_inherited_database_and_do_not_touch_program(self):
        os.environ['ELEVATOR_DATA_DIR'] = str(self.root / 'unrelated-production')
        os.environ['PROGRAMDATA'] = str(self.root / 'ProgramData')
        self.assertEqual(launcher.configure_data_paths(), self.data)
        for key, folder in [('DATA', 'data'), ('STORAGE', 'storage'), ('EXPORT', 'exports'), ('BACKUP', 'backups'), ('LOG', 'logs')]:
            self.assertEqual(Path(os.environ[f'ELEVATOR_{key}_DIR']), self.data / folder)
        self.assertFalse((self.root / 'unrelated-production').exists())
        self.assertFalse((self.program / 'data').exists())

    def test_existing_directory_links_and_wrong_types_are_refused_before_writes(self):
        outside = self.root / 'outside'; outside.mkdir()
        for relative in ('', 'data', 'storage', 'exports', 'backups', 'logs'):
            for symlink in (False, True):
                with self.subTest(relative=relative, symlink=symlink):
                    base = self.root / f'base-{relative or "root"}-{symlink}'
                    target = base / launcher.APP_ID / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if symlink:
                        target.symlink_to(outside, target_is_directory=True)
                    else:
                        target.write_text('preserve', encoding='utf-8')
                    with self.assertRaisesRegex(RuntimeError, '公共数据路径'):
                        launcher.configure_data_paths(base)
        base = self.root / 'linked-ProgramData'
        base.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, '公共数据路径'):
            launcher.configure_data_paths(base)
        self.assertEqual(list(outside.iterdir()), [])

    def test_linked_or_nonfile_log_lock_state_and_temporary_never_modify_target(self):
        outside = self.root / 'outside.txt'; outside.write_text('preserve', encoding='utf-8')
        operations = [
            ('logs/launcher.log', lambda: launcher.configure_logging(self.data)),
            (launcher.LOCK_FILE, lambda: launcher.try_lock(self.data)),
            (launcher.STATE_FILE, lambda: launcher.load_state(self.data, 8765)),
            (launcher.STATE_FILE, lambda: launcher.run_server(self.program, self.data)),
            ('data/elevator.db', lambda: launcher.check_installation(self.program, self.data)),
            (launcher.STATE_FILE + f'.{os.getpid()}.tmp', lambda: launcher.run_server(self.program, self.data)),
        ]
        for relative, operation in operations:
            for symlink in (False, True):
                with self.subTest(relative=relative, symlink=symlink):
                    target = self.data / relative
                    if symlink:
                        target.symlink_to(outside)
                    else:
                        target.mkdir()
                    try:
                        with patch.object(launcher.socket, 'socket'), self.assertRaisesRegex(RuntimeError, '公共数据路径'):
                            operation()
                        self.assertEqual(outside.read_text(encoding='utf-8'), 'preserve')
                    finally:
                        target.unlink() if symlink else target.rmdir()
                    handle = launcher.try_lock(self.data)
                    self.assertIsNotNone(handle); handle.close()
                    (self.data / launcher.LOCK_FILE).unlink()

    def test_windows_reparse_attribute_is_rejected_for_directories_and_files(self):
        original_lstat = Path.lstat
        cases = [
            (self.data.parent, lambda: launcher.configure_data_paths(self.data.parent)),
            (self.data, lambda: launcher.configure_data_paths(self.data.parent)),
            (self.data / 'logs', lambda: launcher.configure_logging(self.data)),
            (self.data / 'logs/launcher.log', lambda: launcher.configure_logging(self.data)),
            (self.data / launcher.LOCK_FILE, lambda: launcher.try_lock(self.data)),
            (self.data / launcher.STATE_FILE, lambda: launcher.load_state(self.data, 8765)),
            (self.data / (launcher.STATE_FILE + f'.{os.getpid()}.tmp'), lambda: launcher.run_server(self.program, self.data)),
        ]
        for target, operation in cases:
            with self.subTest(target=target):
                def lstat(path):
                    if path == target:
                        return SimpleNamespace(st_mode=stat.S_IFDIR if target.is_dir() else stat.S_IFREG,
                                               st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
                    return original_lstat(path)
                with patch.object(Path, 'lstat', lstat), patch.object(launcher.socket, 'socket'), \
                        self.assertRaisesRegex(RuntimeError, '重解析点'):
                    operation()

    def test_check_validates_resources_sqlite_and_never_imports_backend(self):
        with patch.object(launcher.importlib, 'import_module', wraps=launcher.importlib.import_module) as imports:
            launcher.check_installation(self.program, self.data)
        self.assertFalse(any(call.args[0].startswith('backend') for call in imports.call_args_list))
        self.assertFalse((self.data / 'data/elevator.db').exists())
        (self.program / 'frontend/dist/assets/app.js').unlink()
        with self.assertRaisesRegex(RuntimeError, '页面资源缺失'):
            launcher.check_installation(self.program, self.data)
        (self.program / 'frontend/dist/assets/app.js').write_text('// fixture')
        (self.data / 'data/elevator.db').write_bytes(b'not a sqlite database')
        with self.assertRaises(Exception):
            launcher.check_installation(self.program, self.data)

    def test_control_is_loopback_only_and_requires_valid_post_token_without_origin(self):
        calls = []
        async def app(scope, receive, send):
            calls.append('fallback')
        secret = 'ab' * 32
        control = launcher.LocalControl(app, secret, lambda: True, lambda: calls.append('stop'))

        def request(path, method='POST', client='127.0.0.1', headers=()):
            sent = []
            async def send(message):
                sent.append(message)
            asyncio.run(control({'type': 'http', 'path': path, 'method': method, 'client': (client, 1), 'headers': headers}, None, send))
            return sent[0]['status'], json.loads(sent[1]['body'])

        token = [(b'x-launcher-token', secret.encode())]
        for method, client, headers in [('GET', '127.0.0.1', token), ('POST', '192.168.1.5', token),
                                        ('POST', '127.0.0.1', token + [(b'origin', b'null')]),
                                        ('POST', '127.0.0.1', [(b'x-launcher-token', b'wrong')])]:
            self.assertEqual(request(launcher.STOP_PATH, method, client, headers)[0], 403)
        self.assertEqual(calls, [])
        self.assertEqual(request(launcher.STOP_PATH, headers=token), (200, {'stopping': True}))
        self.assertEqual(calls, ['stop'])
        challenge = 'cd' * 32
        status, identity = request(launcher.IDENTITY_PATH, 'GET', headers=[(b'x-launcher-challenge', challenge.encode())])
        self.assertEqual(status, 200)
        self.assertEqual(identity['proof'], launcher.signature(secret, challenge))
        self.assertNotIn(secret, json.dumps(identity))

    def test_invalid_state_fake_identity_and_proxy_settings_never_open_an_occupier(self):
        for invalid in [[], {'app': launcher.APP_ID, 'port': 123, 'secret': []}, {'app': 'other', 'port': 8765, 'secret': 'ab' * 32}]:
            (self.data / launcher.STATE_FILE).write_text(json.dumps(invalid))
            self.assertIsNone(launcher.load_state(self.data, 8765))
        state = {'app': launcher.APP_ID, 'port': 8765, 'secret': 'ab' * 32}
        with patch.object(launcher, 'local_request', return_value={'app': launcher.APP_ID, 'ready': True, 'proof': 'fake'}) as request:
            self.assertFalse(launcher.probe_instance(state))
            self.assertNotIn(state['secret'], str(request.call_args))
        self.assertIsNone(launcher.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.invalid'))

    def test_busy_port_does_not_kill_service_or_open_browser_and_releases_ownership(self):
        with socket.socket() as occupied:
            occupied.bind(('0.0.0.0', 0)); occupied.listen()
            port = occupied.getsockname()[1]
            with patch.object(launcher.webbrowser, 'open') as browser:
                with self.assertRaisesRegex(RuntimeError, '已被其他程序占用'):
                    launcher.run_server(self.program, self.data, port=port)
                browser.assert_not_called()
            self.assertGreaterEqual(occupied.fileno(), 0)
        handle = launcher.try_lock(self.data)
        self.assertIsNotNone(handle); handle.close()
        self.assertFalse((self.data / launcher.STATE_FILE).exists())

    def test_maintenance_blocks_start_before_backend_import_or_database_access(self):
        (self.data / 'maintenance.flag').write_text('installer maintenance', encoding='utf-8')
        with patch.object(launcher, 'check_installation') as check, patch.object(launcher.webbrowser, 'open') as browser:
            with self.assertRaisesRegex(RuntimeError, '正在安装或维护'):
                launcher.run_server(self.program, self.data)
            check.assert_not_called()
            browser.assert_not_called()
        self.assertFalse((self.data / 'data/elevator.db').exists())
        self.assertFalse((self.data / launcher.STATE_FILE).exists())
        handle = launcher.try_lock(self.data)
        self.assertIsNotNone(handle); handle.close()
        launcher.stop_instance(self.data, timeout=1)
        launcher.check_installation(self.program, self.data)

    def test_stop_timeout_returns_failure_without_forcing_or_deleting_data(self):
        handle = launcher.try_lock(self.data)
        self.addCleanup(handle.close)
        preserved = self.data / 'data' / 'business.bin'; preserved.write_bytes(b'business data')
        with self.assertRaisesRegex(RuntimeError, '不会强制结束'):
            launcher.stop_instance(self.data, timeout=0.15)
        self.assertEqual(preserved.read_bytes(), b'business data')
        self.assertIsNone(launcher.try_lock(self.data))
        with patch.object(launcher, 'configure_data_paths', return_value=self.data), \
                patch.object(launcher, 'configure_logging'), patch.object(launcher.logging, 'exception'), \
                patch.object(launcher, 'stop_instance', side_effect=RuntimeError('stop failed')):
            self.assertEqual(launcher.main(['--stop', '--quiet']), 1)

    def test_pythonw_missing_streams_are_redirected_to_a_real_log(self):
        with patch.object(sys, 'stdout', None), patch.object(sys, 'stderr', None), \
                patch.object(launcher.logging, 'basicConfig') as configure:
            launcher.configure_logging(self.data)
            stream = sys.stderr
            self.assertIs(stream, sys.stdout)
            self.assertEqual(Path(stream.name), self.data / 'logs/launcher.log')
            configure.assert_called_once()
            stream.close()

    def test_manual_stop_reports_success_but_quiet_stop_has_no_dialog(self):
        with patch.object(launcher, 'configure_data_paths', return_value=self.data), \
                patch.object(launcher, 'configure_logging'), patch.object(launcher, 'stop_instance') as stop, \
                patch.object(launcher, 'os') as os_api, patch.object(launcher.ctypes, 'windll', create=True) as windll:
            os_api.name = 'nt'
            self.assertEqual(launcher.main(['--stop']), 0)
            stop.assert_called_once_with(self.data)
            windll.user32.MessageBoxW.assert_called_once_with(None, '电梯管理系统已停止。需要使用时请重新打开桌面图标。',
                                                            '昌福里社区27区电梯管理台账', 0x40)
            windll.user32.MessageBoxW.reset_mock()
            self.assertEqual(launcher.main(['--stop', '--quiet']), 0)
            windll.user32.MessageBoxW.assert_not_called()

    def test_real_server_ready_repeat_launch_and_graceful_stop_preserve_data(self):
        port = self.free_port()
        opened = self.root / 'browser-opened.txt'
        repository = Path(__file__).resolve().parents[1]
        code = '''import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from scripts import windows_launcher as launcher
root=Path(sys.argv[2]); data=launcher.configure_data_paths(Path(sys.argv[3]))
launcher.configure_logging(data)
def browser(url):
 with open(sys.argv[5],'a',encoding='utf-8') as stream: stream.write(url+'\\n')
launcher.webbrowser.open=browser
launcher.run_server(root,data,port=int(sys.argv[4]))
'''
        command = [sys.executable, '-c', code, str(repository), str(self.program), str(self.data.parent), str(port), str(opened)]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = launcher.load_state(self.data, port)
            if state and launcher.probe_instance(state) and opened.exists():
                break
            if process.poll() is not None:
                self.fail('server failed: ' + str(process.communicate()))
            time.sleep(0.05)
        else:
            self.fail('server did not become ready')
        self.assertEqual(opened.read_text().splitlines(), [f'http://127.0.0.1:{port}'])
        secret = state['secret']
        with patch.dict(os.environ, {'http_proxy': 'http://127.0.0.1:1', 'HTTP_PROXY': 'http://127.0.0.1:1', 'NO_PROXY': ''}):
            self.assertTrue(launcher.probe_instance(state))
        repeated = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        self.assertEqual(len(opened.read_text().splitlines()), 2)
        self.assertEqual(launcher.load_state(self.data, port)['secret'], secret)
        self.assertIsNone(process.poll())
        preserved = self.data / 'data' / 'business.bin'; preserved.write_bytes(b'unchanged')
        launcher.stop_instance(self.data, port=port, timeout=8)
        stdout, stderr = process.communicate(timeout=8)
        self.assertEqual(process.returncode, 0, stdout + stderr)
        self.assertFalse((self.data / launcher.STATE_FILE).exists())
        self.assertEqual(preserved.read_bytes(), b'unchanged')
        launcher.stop_instance(self.data, port=port, timeout=1)
        restarted = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: restarted.kill() if restarted.poll() is None else None)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = launcher.load_state(self.data, port)
            if state and launcher.probe_instance(state) and len(opened.read_text().splitlines()) == 3:
                break
            if restarted.poll() is not None:
                self.fail('immediate restart failed: ' + str(restarted.communicate()))
            time.sleep(0.05)
        else:
            self.fail('restarted server did not become ready')
        self.assertNotEqual(state['secret'], secret)
        launcher.stop_instance(self.data, port=port, timeout=8)
        stdout, stderr = restarted.communicate(timeout=8)
        self.assertEqual(restarted.returncode, 0, stdout + stderr)
        self.assertFalse((self.data / launcher.STATE_FILE).exists())
        self.assertEqual(preserved.read_bytes(), b'unchanged')


if __name__ == '__main__':
    unittest.main()

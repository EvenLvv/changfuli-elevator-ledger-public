"""Launcher checks use fake application files and temporary per-user data, never the live ledger."""
import asyncio
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts import windows_launcher as launcher
from tests.support import isolated_app

FIXTURE_LEDGER = Path(__file__).resolve().parent / 'fixtures/synthetic-ledger-fixture.xlsx'


class WindowsLauncherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.program = self.root / 'program'
        for relative, content in [
            ('backend/__init__.py', ''),
            ('backend/db.py', '# fake database module'),
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
'''),
            ('frontend/dist/index.html', '<script src="/assets/app.js"></script>'),
            ('frontend/dist/assets/app.js', '// fixture'),
        ]:
            target = self.program / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')
        self.env = patch.dict(os.environ)
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ['PROGRAMDATA'] = str(self.root / 'ProgramData')
        self.data = launcher.configure_data_paths(self.root / 'LocalAppData', program_root=self.program)

    @staticmethod
    def free_port():
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]

    def test_identity_port_title_and_data_separation_from_instdir(self):
        self.assertEqual(launcher.APP_ID, 'ChangfuliElevatorDesktop')
        self.assertNotEqual(launcher.APP_ID, 'ChangfuliElevatorLedger')
        self.assertEqual(launcher.PORT, 8766)
        self.assertIn('2.0', launcher.WINDOW_TITLE)
        self.assertNotEqual(launcher.LOCK_FILE, 'runtime-instance.lock')
        self.assertNotEqual(launcher.STATE_FILE, 'runtime-instance.json')

        os.environ['ELEVATOR_DATA_DIR'] = str(self.root / 'unrelated-production')
        os.environ['WEBVIEW2_USER_DATA_FOLDER'] = str(self.program / 'WebView2')
        os.environ['LOCALAPPDATA'] = str(self.root / 'LocalAppData')
        resolved = launcher.configure_data_paths(program_root=self.program)
        self.assertEqual(resolved, self.data)
        self.assertNotEqual(resolved, self.program)
        self.assertNotIn(self.program.resolve(), resolved.resolve().parents)

        for key, folder in [('DATA', 'data'), ('STORAGE', 'storage'), ('EXPORT', 'exports'),
                            ('BACKUP', 'backups'), ('LOG', 'logs')]:
            configured = Path(os.environ[f'ELEVATOR_{key}_DIR']).resolve()
            self.assertEqual(configured, (self.data / folder).resolve())
            self.assertNotIn(self.program.resolve(), configured.parents)

        webview_folder = Path(os.environ['WEBVIEW2_USER_DATA_FOLDER']).resolve()
        self.assertEqual(webview_folder, (self.data / 'WebView2').resolve())
        self.assertNotIn('ChangfuliElevatorLedger', str(webview_folder))
        self.assertNotIn(self.program.resolve(), webview_folder.parents)
        self.assertFalse((self.root / 'unrelated-production').exists())
        self.assertFalse((self.program / 'data').exists())

        # Data root inside, equal to, or enclosing INSTDIR must be rejected.
        with self.assertRaisesRegex(RuntimeError, '数据目录必须独立于程序安装目录'):
            launcher.configure_data_paths(self.program, program_root=self.program)
        with self.assertRaisesRegex(RuntimeError, '数据目录必须独立于程序安装目录'):
            launcher.configure_data_paths(self.root, program_root=self.root / launcher.APP_ID / 'installed-app')

    def test_elevated_check_never_creates_admin_database_and_data_folder_opens_user_root(self):
        admin_local = self.root / 'ElevatedAdminLocalAppData'
        user_local = self.root / 'InteractiveUserLocalAppData'
        admin_local.mkdir()
        user_local.mkdir()
        with patch.dict(os.environ, LOCALAPPDATA=str(admin_local)), \
                patch.object(launcher, 'check_installation') as check:
            self.assertEqual(launcher.main(['--check', '--quiet']), 0)
            check.assert_called_once()
            self.assertIsNone(check.call_args.args[1])
        self.assertFalse((admin_local / launcher.APP_ID).exists())

        with patch.dict(os.environ, LOCALAPPDATA=str(user_local)), \
                patch.object(launcher.os, 'startfile', create=True) as startfile:
            self.assertEqual(launcher.main(['--data-folder']), 0)
            startfile.assert_called_once_with(str(user_local / launcher.APP_ID))
        self.assertFalse((user_local / launcher.APP_ID / 'data/elevator.db').exists())

    def test_existing_directory_links_and_wrong_types_are_refused_before_writes(self):
        outside = self.root / 'outside'; outside.mkdir()
        for relative in ('', 'data', 'storage', 'exports', 'backups', 'logs', 'WebView2'):
            for symlink in (False, True):
                with self.subTest(relative=relative, symlink=symlink):
                    base = self.root / f'base-{relative or "root"}-{symlink}'
                    target = base / launcher.APP_ID / relative if relative else base / launcher.APP_ID
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if symlink:
                        target.symlink_to(outside, target_is_directory=True)
                    else:
                        target.write_text('preserve', encoding='utf-8')
                    with self.assertRaisesRegex(RuntimeError, '本地数据路径'):
                        launcher.configure_data_paths(base, program_root=self.program)
        base = self.root / 'linked-LocalAppData'
        base.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, '本地数据路径'):
            launcher.configure_data_paths(base, program_root=self.program)
        self.assertEqual(list(outside.iterdir()), [])

    def test_linked_or_nonfile_log_lock_state_and_temporary_never_modify_target(self):
        outside = self.root / 'outside.txt'; outside.write_text('preserve', encoding='utf-8')
        operations = [
            ('logs/launcher.log', lambda: launcher.configure_logging(self.data)),
            (launcher.LOCK_FILE, lambda: launcher.try_lock(self.data)),
            (launcher.STATE_FILE, lambda: launcher.load_state(self.data, 8766)),
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
                        with patch.object(launcher.socket, 'socket'), self.assertRaisesRegex(RuntimeError, '本地数据路径'):
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
            (self.data.parent, lambda: launcher.configure_data_paths(self.data.parent, program_root=self.program)),
            (self.data, lambda: launcher.configure_data_paths(self.data.parent, program_root=self.program)),
            (self.data / 'logs', lambda: launcher.configure_logging(self.data)),
            (self.data / 'logs/launcher.log', lambda: launcher.configure_logging(self.data)),
            (self.data / launcher.LOCK_FILE, lambda: launcher.try_lock(self.data)),
            (self.data / launcher.STATE_FILE, lambda: launcher.load_state(self.data, 8766)),
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
        if os.name != 'nt':
            self.assertNotIn('webview', [call.args[0] for call in imports.call_args_list])
        self.assertFalse((self.data / 'data/elevator.db').exists())
        (self.program / 'frontend/dist/assets/app.js').unlink()
        with self.assertRaisesRegex(RuntimeError, '页面资源缺失'):
            launcher.check_installation(self.program, self.data)
        (self.program / 'frontend/dist/assets/app.js').write_text('// fixture')
        (self.data / 'data/elevator.db').write_bytes(b'not a sqlite database')
        with self.assertRaises(Exception):
            launcher.check_installation(self.program, self.data)

    def test_windows_check_verifies_desktop_dependencies_without_opening_window(self):
        with patch.object(launcher, 'os') as os_api, patch.object(launcher.sys, 'version_info', (3, 12)), \
                patch.object(launcher.importlib, 'import_module') as imports, \
                patch.object(launcher, 'open_operator_window') as window:
            os_api.name = 'nt'
            launcher.check_installation(self.program, self.data)
            imports.assert_any_call('webview')
            imports.assert_any_call('clr')
            window.assert_not_called()

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
        self.assertEqual(identity['app'], 'ChangfuliElevatorDesktop')
        self.assertEqual(identity['version'], '2.0.0')
        self.assertEqual(identity['proof'], launcher.signature(secret, challenge))
        self.assertNotIn(secret, json.dumps(identity))

    def test_invalid_state_fake_identity_and_leftover_1x_instance_are_ignored(self):
        legacy_secret = 'ab' * 32
        for invalid in [
            [],
            {'app': launcher.APP_ID, 'port': 123, 'secret': []},
            {'app': 'other', 'port': 8766, 'secret': legacy_secret},
            {'app': 'ChangfuliElevatorLedger', 'port': 8765, 'secret': legacy_secret},
            {'app': 'ChangfuliElevatorLedger', 'port': 8766, 'secret': legacy_secret},
        ]:
            (self.data / launcher.STATE_FILE).write_text(json.dumps(invalid), encoding='utf-8')
            self.assertIsNone(launcher.load_state(self.data, 8766))
            self.assertIsNone(launcher.load_state(self.data, 8765))

        state = {'app': launcher.APP_ID, 'port': 8766, 'secret': legacy_secret}
        with patch.object(launcher, 'local_request', return_value={'app': launcher.APP_ID, 'ready': True, 'proof': 'fake'}) as request:
            self.assertFalse(launcher.probe_instance(state))
            self.assertNotIn(state['secret'], str(request.call_args))

        # Mock a live 1.x server responding with ChangfuliElevatorLedger and a valid HMAC proof.
        v1_requests = []

        class LegacyHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                v1_requests.append(('GET', self.path))
                challenge = self.headers.get('X-Launcher-Challenge', '')
                body = {'ok': True} if self.path == '/api/health' else {
                    'app': 'ChangfuliElevatorLedger',
                    'ready': True,
                    'proof': launcher.signature(legacy_secret, challenge) if challenge else '',
                }
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(body).encode('utf-8'))

            def do_POST(self):
                v1_requests.append(('POST', self.path))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"stopping":true}')

            def log_message(self, *args):
                pass

        legacy_server = ThreadingHTTPServer(('127.0.0.1', 0), LegacyHandler)
        legacy_thread = threading.Thread(target=legacy_server.serve_forever, daemon=True)
        legacy_thread.start()
        self.addCleanup(lambda: (legacy_server.shutdown(), legacy_server.server_close()))

        # Even if a 1.x state file exists in ProgramData\ChangfuliElevatorLedger and holds runtime-instance.lock,
        # 2.0 stop_instance and probe_instance never attach to or stop the 1.x server.
        legacy_dir = self.root / 'ProgramData/ChangfuliElevatorLedger'
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / 'runtime-instance.json').write_text(json.dumps({
            'app': 'ChangfuliElevatorLedger',
            'pid': 99999,
            'port': legacy_server.server_port,
            'secret': legacy_secret,
        }), encoding='utf-8')
        legacy_lock = open(legacy_dir / 'runtime-instance.lock', 'a+b', buffering=0)
        self.addCleanup(legacy_lock.close)
        import fcntl
        fcntl.flock(legacy_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        self.assertFalse(launcher.probe_instance({
            'app': 'ChangfuliElevatorLedger',
            'port': legacy_server.server_port,
            'secret': legacy_secret,
        }))
        # Spoofed server returning ChangfuliElevatorLedger when state claims ChangfuliElevatorDesktop is rejected too.
        self.assertFalse(launcher.probe_instance({
            'app': launcher.APP_ID,
            'port': legacy_server.server_port,
            'secret': legacy_secret,
        }))
        launcher.stop_instance(self.data, port=legacy_server.server_port, timeout=0.3)
        self.assertFalse(any(method == 'POST' for method, _ in v1_requests))
        self.assertIsNone(launcher.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.invalid'))

    def test_legacy_v1_data_migration_copies_when_empty_preserves_old_and_never_overwrites(self):
        legacy_program_data = self.root / 'ProgramData'
        legacy_root = legacy_program_data / 'ChangfuliElevatorLedger'
        for folder in ('data', 'storage/photos', 'exports', 'backups', 'logs'):
            (legacy_root / folder).mkdir(parents=True, exist_ok=True)

        legacy_db = legacy_root / 'data/elevator.db'
        with closing(sqlite3.connect(legacy_db)) as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('CREATE TABLE buildings (id INTEGER PRIMARY KEY, name TEXT NOT NULL)')
            conn.execute("INSERT INTO buildings(name) VALUES ('迁移测试18栋')")
            conn.commit()
        (legacy_root / 'storage/photos/site-1.png').write_bytes(b'fake-png-content')
        (legacy_root / 'exports/archive-1.docx').write_bytes(b'fake-docx-content')
        (legacy_root / 'backups/backup-1.zip').write_bytes(b'fake-zip-content')
        (legacy_root / 'logs/system.log').write_text('legacy log entry\n', encoding='utf-8')

        # 1) New 2.0 data root has no elevator.db -> safe copy succeeds and writes migration record.
        self.assertFalse((self.data / 'data/elevator.db').exists())
        migrated = launcher.migrate_legacy_data(self.data, program_data=legacy_program_data)
        self.assertTrue(migrated)
        self.assertTrue((self.data / 'data/elevator.db').is_file())
        with closing(sqlite3.connect(self.data / 'data/elevator.db')) as conn:
            rows = conn.execute('SELECT name FROM buildings').fetchall()
        self.assertEqual(rows, [('迁移测试18栋',)])
        self.assertEqual((self.data / 'storage/photos/site-1.png').read_bytes(), b'fake-png-content')
        self.assertEqual((self.data / 'exports/archive-1.docx').read_bytes(), b'fake-docx-content')
        self.assertEqual((self.data / 'backups/backup-1.zip').read_bytes(), b'fake-zip-content')

        record = json.loads((self.data / launcher.MIGRATION_FILE).read_text(encoding='utf-8'))
        self.assertEqual(record['source_app_id'], 'ChangfuliElevatorLedger')
        self.assertEqual(record['target_app_id'], 'ChangfuliElevatorDesktop')
        self.assertEqual(set(record['copied_folders']), {'data', 'storage', 'exports', 'backups'})

        # Old 1.x directory and files must still be completely present and intact.
        self.assertTrue(legacy_db.is_file())
        self.assertEqual((legacy_root / 'storage/photos/site-1.png').read_bytes(), b'fake-png-content')
        self.assertEqual((legacy_root / 'exports/archive-1.docx').read_bytes(), b'fake-docx-content')
        self.assertEqual((legacy_root / 'backups/backup-1.zip').read_bytes(), b'fake-zip-content')
        self.assertEqual((legacy_root / 'logs/system.log').read_text(encoding='utf-8'), 'legacy log entry\n')

        # 2) When 2.0 already has its own database, migration must NOT overwrite it and must NOT fail.
        with closing(sqlite3.connect(self.data / 'data/elevator.db')) as conn:
            conn.execute("DELETE FROM buildings")
            conn.execute("INSERT INTO buildings(name) VALUES ('2.0独立新建27栋')")
            conn.commit()
        with closing(sqlite3.connect(legacy_db)) as conn:
            conn.execute("INSERT INTO buildings(name) VALUES ('旧版后续记录99栋')")
            conn.commit()
        (legacy_root / 'storage/photos/only-in-old.png').write_bytes(b'do-not-copy-when-db-exists')

        migrated_again = launcher.migrate_legacy_data(self.data, program_data=legacy_program_data)
        self.assertFalse(migrated_again)
        with closing(sqlite3.connect(self.data / 'data/elevator.db')) as conn:
            rows = conn.execute('SELECT name FROM buildings').fetchall()
        self.assertEqual(rows, [('2.0独立新建27栋',)])
        self.assertFalse((self.data / 'storage/photos/only-in-old.png').exists())
        self.assertTrue((legacy_root / 'storage/photos/only-in-old.png').is_file())

    def test_first_launch_seed_imports_synthetic_fixture_with_no_login_operator(self):
        with isolated_app() as (client, paths):
            seeded = paths['DATA'].parent / 'seed/official-ledger.xlsx'
            seeded.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(FIXTURE_LEDGER, seeded)
            from backend import main
            main.seed_empty_ledger(main.actor())
            self.assertEqual(client.get('/api/setup/status').json(), {'needed': False})
            elevators = client.get('/api/elevators').json()
            self.assertEqual(len(elevators), 9)
            report = json.loads((paths['LOGS'] / 'seed-import-report.json').read_text(encoding='utf-8'))
            self.assertTrue(report['committed'])

    def test_busy_port_does_not_kill_service_or_open_window_and_releases_ownership(self):
        with socket.socket() as occupied:
            occupied.bind(('0.0.0.0', 0)); occupied.listen()
            port = occupied.getsockname()[1]
            with patch.object(launcher, 'open_operator_window') as window:
                with self.assertRaisesRegex(RuntimeError, '已被其他程序占用'):
                    launcher.run_server(self.program, self.data, port=port)
                window.assert_not_called()
            self.assertGreaterEqual(occupied.fileno(), 0)
        handle = launcher.try_lock(self.data)
        self.assertIsNotNone(handle); handle.close()
        self.assertFalse((self.data / launcher.STATE_FILE).exists())

    def test_maintenance_blocks_start_before_backend_import_or_database_access(self):
        for flag_location in (self.data / 'maintenance.flag', self.program / 'maintenance.flag'):
            with self.subTest(flag=flag_location.parent.name):
                flag_location.write_text('installer maintenance', encoding='utf-8')
                try:
                    with patch.object(launcher, 'check_installation') as check, \
                            patch.object(launcher, 'open_operator_window') as window:
                        with self.assertRaisesRegex(RuntimeError, '正在安装或维护'):
                            launcher.run_server(self.program, self.data)
                        check.assert_not_called()
                        window.assert_not_called()
                finally:
                    flag_location.unlink()
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
            windll.user32.MessageBoxW.assert_called_once_with(
                None, '电梯管理系统 2.0 已停止。需要使用时请重新打开桌面图标。', launcher.WINDOW_TITLE, 0x40
            )
            windll.user32.MessageBoxW.reset_mock()
            self.assertEqual(launcher.main(['--stop', '--quiet']), 0)
            windll.user32.MessageBoxW.assert_not_called()

    def test_repeat_launch_restores_only_own_2_0_window_never_1x_or_browser(self):
        with patch.object(launcher.ctypes, 'windll', create=True) as windll, patch('webbrowser.open') as browser:
            api = windll.user32

            def find_window(cls, title):
                # Simulate an old 1.x window still open alongside our 2.0 window.
                if title == '昌福里社区电梯管理系统':
                    raise AssertionError('Must never query the 1.x window title')
                return 123 if title == '昌福里社区电梯管理系统 2.0' else 0

            api.FindWindowW.side_effect = find_window

            def get_owner(hwnd, owner):
                owner._obj.value = 45
                return 1

            api.GetWindowThreadProcessId.side_effect = get_owner
            launcher.activate_existing_window(45)
            api.FindWindowW.assert_called_once_with(None, '昌福里社区电梯管理系统 2.0')
            api.ShowWindow.assert_called_once()
            api.SetForegroundWindow.assert_called_once()
            api.MessageBoxW.assert_not_called()
            api.SetForegroundWindow.reset_mock()

            launcher.activate_existing_window(67)
            api.SetForegroundWindow.assert_not_called()
            self.assertIn('2.0 已在运行', api.MessageBoxW.call_args.args[1])
            api.MessageBoxW.reset_mock()
            api.SetForegroundWindow.return_value = 0
            launcher.activate_existing_window(45)
            api.MessageBoxW.assert_called_once()
            browser.assert_not_called()

    def test_desktop_window_settings_stop_and_webview2_failures(self):
        class Event:
            def __iadd__(self, callback):
                return callback  # Retain the registered handler for the fake GUI loop.

        for outcome in ('stop', 'legacy renderer', 'initialization failure', 'start exception'):
            with self.subTest(outcome=outcome):
                stopped = threading.Event()
                events = SimpleNamespace(initialized=Event(), before_show=Event(), shown=Event(),
                                         closed=threading.Event())
                control = SimpleNamespace(CoreWebView2InitializationCompleted=Event())
                window = Mock(events=events, native=SimpleNamespace(webview=control))
                gui = Mock(settings={}, renderer='mshtml' if outcome == 'legacy renderer' else 'edgechromium')
                gui.create_window.return_value = window

                def start(**kwargs):
                    if outcome == 'start exception':
                        raise OSError('renderer startup failed')
                    if not events.initialized(gui.renderer):
                        return
                    events.before_show()
                    if outcome == 'initialization failure':
                        control.CoreWebView2InitializationCompleted(None, SimpleNamespace(
                            IsSuccess=False, InitializationException='synthetic failure'))
                    else:
                        view = Mock()
                        control.CoreWebView2InitializationCompleted(view, SimpleNamespace(IsSuccess=True))
                        self.assertIs(view.CoreWebView2.Settings.AreBrowserAcceleratorKeysEnabled, True)
                        stopped.set()
                    self.assertTrue(stopped.is_set())
                    events.shown()

                gui.start.side_effect = start
                icon = self.program / (launcher.ICON_NAME if outcome == 'stop' else f'scripts/{launcher.ICON_NAME}')
                icon.parent.mkdir(exist_ok=True)
                icon.touch()
                local_base = self.root / 'LocalAppData'
                with patch.dict(sys.modules, webview=gui), patch.dict(os.environ, LOCALAPPDATA=str(local_base)), \
                        patch('webbrowser.open') as browser:
                    if outcome == 'stop':
                        launcher.open_operator_window(self.program, 'http://127.0.0.1:8766', stopped)
                    else:
                        with self.assertRaisesRegex(RuntimeError, '请安装或修复 Microsoft Edge WebView2 Runtime'):
                            launcher.open_operator_window(self.program, 'http://127.0.0.1:8766', stopped)
                    browser.assert_not_called()
                    expected_wv2 = str(local_base / 'ChangfuliElevatorDesktop' / 'WebView2')
                    self.assertEqual(os.environ['WEBVIEW2_USER_DATA_FOLDER'], expected_wv2)
                    self.assertEqual(gui.start.call_args.kwargs['storage_path'], expected_wv2)
                gui.create_window.assert_called_once_with(
                    '昌福里社区电梯管理系统 2.0', 'http://127.0.0.1:8766',
                    width=1440, height=900, maximized=True, text_select=True,
                )
                self.assertEqual(gui.start.call_args.kwargs['gui'], 'edgechromium')
                self.assertEqual(gui.start.call_args.kwargs['icon'], str(icon))
                self.assertTrue(gui.settings['ALLOW_DOWNLOADS'])
                if outcome in ('stop', 'initialization failure'):
                    window.destroy.assert_called_once()
                else:
                    window.destroy.assert_not_called()
                icon.unlink()

    def test_webview2_error_is_shown_in_windows_dialog(self):
        with patch.object(launcher, 'configure_data_paths', return_value=self.data), \
                patch.object(launcher, 'configure_logging'), patch.object(launcher.logging, 'exception'), \
                patch.object(launcher, 'run_server', side_effect=RuntimeError(launcher.WEBVIEW2_ERROR)), \
                patch.object(launcher, 'os', name='windows_os') as os_api, \
                patch.object(launcher.ctypes, 'windll', create=True) as windll:
            os_api.name = 'nt'
            self.assertEqual(launcher.main([]), 1)
            msg = windll.user32.MessageBoxW.call_args.args[1]
            self.assertIn(launcher.WEBVIEW2_ERROR, msg)
            self.assertIn(str(self.data), msg)
            self.assertNotIn('ChangfuliElevatorLedger', msg)
            self.assertNotIn(' browser', msg)

    def test_real_server_ready_repeat_launch_and_graceful_stop_preserve_data(self):
        port = self.free_port()
        opened = self.root / 'window-opened.txt'
        repository = Path(__file__).resolve().parents[1]
        code = '''import os, sys, threading, webbrowser
from pathlib import Path
sys.path.insert(0,sys.argv[1])
os.environ['PROGRAMDATA']=sys.argv[6]
from scripts import windows_launcher as launcher
root=Path(sys.argv[2]); data=launcher.configure_data_paths(Path(sys.argv[3]), program_root=root)
launcher.configure_logging(data)
def unexpected_browser(*args, **kwargs):
 raise AssertionError('Launcher opened the system browser')
webbrowser.open=unexpected_browser
def window(root, url, stopped):
 assert threading.current_thread() is threading.main_thread()
 assert os.environ.get('WEBVIEW2_USER_DATA_FOLDER') == str(data / 'WebView2')
 assert launcher.probe_instance(launcher.load_state(data, int(sys.argv[4])))
 with open(sys.argv[5],'a',encoding='utf-8') as stream: stream.write(url+'\\n')
 while not stopped.wait(0.05):
  if (root/'close-window').exists(): return
def activate(pid, quiet):
 print('activate', pid)
launcher.open_operator_window=window
launcher.activate_existing_window=activate
launcher.run_server(root,data,port=int(sys.argv[4]))
'''
        command = [
            sys.executable, '-c', code,
            str(repository), str(self.program), str(self.data.parent),
            str(port), str(opened), str(self.root / 'ProgramData'),
        ]
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
        self.assertEqual(state['app'], 'ChangfuliElevatorDesktop')
        secret = state['secret']
        with patch.dict(os.environ, {'http_proxy': 'http://127.0.0.1:1', 'HTTP_PROXY': 'http://127.0.0.1:1', 'NO_PROXY': ''}):
            self.assertTrue(launcher.probe_instance(state))
        repeated = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        self.assertEqual(repeated.stdout.strip(), f'activate {process.pid}')
        self.assertEqual(opened.read_text().splitlines(), [f'http://127.0.0.1:{port}'])
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
            if state and launcher.probe_instance(state) and len(opened.read_text().splitlines()) == 2:
                break
            if restarted.poll() is not None:
                self.fail('immediate restart failed: ' + str(restarted.communicate()))
            time.sleep(0.05)
        else:
            self.fail('restarted server did not become ready')
        self.assertNotEqual(state['secret'], secret)
        (self.program / 'close-window').touch()
        stdout, stderr = restarted.communicate(timeout=8)
        self.assertEqual(restarted.returncode, 0, stdout + stderr)
        self.assertFalse((self.data / launcher.STATE_FILE).exists())
        self.assertEqual(preserved.read_bytes(), b'unchanged')
        self.assertFalse(launcher.probe_instance(state))
        handle = launcher.try_lock(self.data)
        self.assertIsNotNone(handle)
        handle.close()


if __name__ == '__main__':
    unittest.main()

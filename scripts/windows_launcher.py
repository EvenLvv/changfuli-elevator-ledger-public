"""Installed Windows entry point. Keep application files separate from per-user business data."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import ctypes
from ctypes import wintypes
import errno
import hashlib
import hmac
import importlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import sqlite3
import stat
import struct
import sys
import threading
import time
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

APP_ID = 'ChangfuliElevatorDesktop'
LEGACY_APP_ID = 'ChangfuliElevatorLedger'
APP_VERSION = '2.0.2'
WINDOW_TITLE = '昌福里社区电梯管理系统 2.0.2'
ICON_NAME = 'desktop-app-2.0.ico'
WEBVIEW2_ERROR = '无法打开桌面窗口。请安装或修复 Microsoft Edge WebView2 Runtime，然后重新打开电梯管理系统。'
PORT = 8766
START_TIMEOUT = 45
STOP_TIMEOUT = 45
IDENTITY_PATH = '/_launcher/identity'
STOP_PATH = '/_launcher/stop'
STATE_FILE = 'desktop-instance-v2.json'
LOCK_FILE = 'desktop-instance-v2.lock'
MIGRATION_FILE = 'migration-from-v1.json'
MIGRATED_FOLDERS = ('data', 'storage', 'exports', 'backups')
SKIPPED_LEGACY_DATA_FILES = {'elevator.db', 'elevator.db-wal', 'elevator.db-shm', 'elevator.db-journal'}


def _is_reparse_or_wrong_type(info, *, directory):
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    return bool(
        stat.S_ISLNK(info.st_mode)
        or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        or not expected_type(info.st_mode)
    )


def checked_data_path(data_root, relative, *, directory=False):
    path = data_root / relative if relative else data_root
    paths = [path]
    while paths[-1] != data_root.parent:
        paths.append(paths[-1].parent)
    # shortcut: preflight rejects existing links; concurrent replacement needs handle-based Windows I/O.
    for current in reversed(paths):
        try:
            info = current.lstat()
        except FileNotFoundError:
            pass
        else:
            is_directory = directory if current == path else True
            if _is_reparse_or_wrong_type(info, directory=is_directory):
                raise RuntimeError(f'本地数据路径包含链接、重解析点或类型不符：{current}。请联系管理员检查。')
    return path


def resolve_data_root(local_app_data=None, *, program_root=None):
    base = Path(local_app_data if local_app_data is not None else os.environ.get('LOCALAPPDATA', ''))
    if not base.is_absolute():
        raise RuntimeError('无法确定当前用户的本地数据目录（LOCALAPPDATA）。')
    data_root = base / APP_ID
    program = Path(os.path.abspath(program_root or Path(__file__).resolve().parents[1]))
    candidate = Path(os.path.abspath(data_root))
    if candidate == program or program in candidate.parents or candidate in program.parents:
        raise RuntimeError(f'数据目录必须独立于程序安装目录：{data_root}')
    checked_data_path(data_root, '', directory=True)
    return data_root


def configure_seed_ledger(program_root=None):
    program = Path(os.path.abspath(program_root or Path(__file__).resolve().parents[1]))
    seed_file = program / 'seed' / 'official-ledger.xlsx'
    if _safe_legacy_entry(seed_file, directory=False):
        os.environ['ELEVATOR_SEED_LEDGER'] = str(seed_file)
        return seed_file
    configured = os.environ.get('ELEVATOR_SEED_LEDGER', '')
    if configured:
        candidate = Path(configured)
        if candidate.is_absolute() and _safe_legacy_entry(candidate, directory=False):
            return candidate
        os.environ.pop('ELEVATOR_SEED_LEDGER', None)
    return None


def configure_data_paths(local_app_data=None, *, program_root=None):
    data_root = resolve_data_root(local_app_data, program_root=program_root)
    for key, folder in [('DATA', 'data'), ('STORAGE', 'storage'), ('EXPORT', 'exports'),
                        ('BACKUP', 'backups'), ('LOG', 'logs')]:
        path = checked_data_path(data_root, folder, directory=True)
        path.mkdir(parents=True, exist_ok=True)
        checked_data_path(data_root, folder, directory=True)
        # Installed versions use the per-user data root; inherited overrides never select another database.
        os.environ[f'ELEVATOR_{key}_DIR'] = str(path)
    webview_dir = checked_data_path(data_root, 'WebView2', directory=True)
    webview_dir.mkdir(parents=True, exist_ok=True)
    checked_data_path(data_root, 'WebView2', directory=True)
    os.environ['WEBVIEW2_USER_DATA_FOLDER'] = str(webview_dir)
    configure_seed_ledger(program_root)
    return data_root


def _safe_legacy_entry(path, *, directory):
    try:
        info = path.lstat()
    except OSError:
        return False
    return not _is_reparse_or_wrong_type(info, directory=directory)


def _copy_legacy_tree(source_dir, target_dir, data_root, *, skip_names=()):
    copied = 0
    stack = [source_dir]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for entry in entries:
            try:
                info = entry.lstat()
            except OSError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                continue
            relative = entry.relative_to(source_dir)
            if stat.S_ISDIR(info.st_mode):
                destination_dir = target_dir / relative
                checked_data_path(data_root, destination_dir.relative_to(data_root), directory=True)
                destination_dir.mkdir(parents=True, exist_ok=True)
                stack.append(entry)
            elif stat.S_ISREG(info.st_mode):
                if current == source_dir and entry.name in skip_names:
                    continue
                destination_file = target_dir / relative
                checked_data_path(data_root, destination_file.relative_to(data_root), directory=False)
                destination_file.parent.mkdir(parents=True, exist_ok=True)
                if not destination_file.exists():
                    shutil.copy2(entry, destination_file)
                    copied += 1
    return copied


def _count_db_elevators(conn, *, active_only=False):
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='elevators'"
    ).fetchone()
    if not has_table:
        return 0
    if active_only:
        columns = {row[1] for row in conn.execute('PRAGMA table_info(elevators)')}
        if 'deleted_at' in columns:
            return conn.execute('SELECT COUNT(*) FROM elevators WHERE deleted_at IS NULL').fetchone()[0]
    return conn.execute('SELECT COUNT(*) FROM elevators').fetchone()[0]


def _inspect_staged_sqlite(source_db, stage_dir, output_db=None):
    """Copy a SQLite DB (and optional WAL/SHM sidecars) into stage_dir and verify quick_check."""
    shutil.rmtree(stage_dir, ignore_errors=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    staged_db = stage_dir / 'elevator.db'
    shutil.copy2(source_db, staged_db)
    for sidecar in ('elevator.db-wal', 'elevator.db-shm'):
        sidecar_src = source_db.parent / sidecar
        if _safe_legacy_entry(sidecar_src, directory=False):
            shutil.copy2(sidecar_src, stage_dir / sidecar)
    snapshot = output_db if output_db is not None else (stage_dir / 'snapshot.db')
    snapshot.unlink(missing_ok=True)
    with closing(sqlite3.connect(staged_db)) as source_conn, closing(sqlite3.connect(snapshot)) as target_conn:
        source_conn.backup(target_conn)
    with closing(sqlite3.connect(snapshot.resolve().as_uri() + '?mode=ro', uri=True)) as check_conn:
        if check_conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise sqlite3.DatabaseError('database failed quick_check')
        total_elevators = _count_db_elevators(check_conn, active_only=False)
        active_elevators = _count_db_elevators(check_conn, active_only=True)
    return total_elevators, active_elevators


def _legacy_candidate_roots(data_root, program_data=None, local_app_data=None, roaming_app_data=None):
    raw_bases = [
        program_data if program_data is not None else os.environ.get('PROGRAMDATA', ''),
        local_app_data if local_app_data is not None else os.environ.get('LOCALAPPDATA', ''),
        roaming_app_data if roaming_app_data is not None else os.environ.get('APPDATA', ''),
    ]
    resolved_target = Path(os.path.abspath(data_root))
    seen = set()
    roots = []
    for raw in raw_bases:
        if not raw:
            continue
        base = Path(raw)
        if not base.is_absolute() or not _safe_legacy_entry(base, directory=True):
            continue
        legacy_root = base / LEGACY_APP_ID
        resolved_legacy = Path(os.path.abspath(legacy_root))
        if resolved_legacy in seen or resolved_legacy == resolved_target:
            continue
        if not _safe_legacy_entry(legacy_root, directory=True):
            continue
        legacy_data_dir = legacy_root / 'data'
        legacy_db = legacy_data_dir / 'elevator.db'
        if _safe_legacy_entry(legacy_data_dir, directory=True) and _safe_legacy_entry(legacy_db, directory=False):
            seen.add(resolved_legacy)
            roots.append(legacy_root)
    return roots


def migrate_legacy_data(data_root, program_data=None, *, local_app_data=None, roaming_app_data=None):
    """Safely copy 1.x ledger into an absent or elevator-empty 2.0 data root without modifying 1.x files."""
    new_data_dir = checked_data_path(data_root, 'data', directory=True)
    new_db = checked_data_path(data_root, 'data/elevator.db')
    for sidecar in ('data/elevator.db-wal', 'data/elevator.db-shm'):
        checked_data_path(data_root, sidecar)

    new_db_exists = new_db.exists()
    if new_db_exists:
        inspect_dir = new_data_dir / f'.inspect-v2-{os.getpid()}'
        try:
            existing_total, _ = _inspect_staged_sqlite(new_db, inspect_dir)
        except (OSError, sqlite3.Error):
            # Never overwrite an unreadable or corrupt 2.0 database; check_installation reports it.
            return False
        finally:
            shutil.rmtree(inspect_dir, ignore_errors=True)
        if existing_total > 0:
            return False

    candidates = _legacy_candidate_roots(
        data_root, program_data=program_data, local_app_data=local_app_data, roaming_app_data=roaming_app_data
    )
    if not candidates:
        return False

    new_data_dir.mkdir(parents=True, exist_ok=True)
    stage_dir = new_data_dir / f'.legacy-migrate-{os.getpid()}'
    temp_db = checked_data_path(data_root, f'data/elevator.db.{os.getpid()}.tmp')
    fallback_db = checked_data_path(data_root, f'data/elevator.db.{os.getpid()}.fallback.tmp')
    chosen_root = None
    chosen_elevators = 0
    fallback_root = None

    try:
        for candidate_root in candidates:
            candidate_db = candidate_root / 'data/elevator.db'
            try:
                _, active_elevators = _inspect_staged_sqlite(candidate_db, stage_dir, output_db=temp_db)
            except (OSError, sqlite3.Error):
                logging.warning('检测到 1.x 数据目录 %s，但旧数据库无法安全复制，已跳过该候选目录。',
                                candidate_root, exc_info=True)
                temp_db.unlink(missing_ok=True)
                continue
            if active_elevators > 0:
                chosen_root = candidate_root
                chosen_elevators = active_elevators
                break
            if not new_db_exists and fallback_root is None:
                temp_db.replace(fallback_db)
                fallback_root = candidate_root
            else:
                temp_db.unlink(missing_ok=True)

        if chosen_root is None and fallback_root is not None:
            fallback_db.replace(temp_db)
            chosen_root = fallback_root
            chosen_elevators = 0
        if chosen_root is None:
            return False

        legacy_data_dir = chosen_root / 'data'
        copied_folders = ['data']
        copied_files = 1 + _copy_legacy_tree(
            legacy_data_dir, new_data_dir, data_root, skip_names=SKIPPED_LEGACY_DATA_FILES
        )
        for folder in MIGRATED_FOLDERS[1:]:
            source_folder = chosen_root / folder
            if _safe_legacy_entry(source_folder, directory=True):
                target_folder = checked_data_path(data_root, folder, directory=True)
                target_folder.mkdir(parents=True, exist_ok=True)
                copied_files += _copy_legacy_tree(source_folder, target_folder, data_root)
                copied_folders.append(folder)

        checked_data_path(data_root, 'data/elevator.db')
        if new_db.exists():
            inspect_dir = new_data_dir / f'.inspect-v2-{os.getpid()}'
            try:
                current_total, _ = _inspect_staged_sqlite(new_db, inspect_dir)
            finally:
                shutil.rmtree(inspect_dir, ignore_errors=True)
            if current_total > 0:
                return False
            with closing(sqlite3.connect(temp_db)) as src_conn, closing(sqlite3.connect(new_db)) as dst_conn:
                src_conn.backup(dst_conn)
            temp_db.unlink(missing_ok=True)
        else:
            for sidecar in ('data/elevator.db-wal', 'data/elevator.db-shm'):
                checked_data_path(data_root, sidecar).unlink(missing_ok=True)
            temp_db.replace(new_db)
    except (OSError, sqlite3.Error):
        logging.warning('自动迁移 1.x 数据失败，已保留原目录与当前状态。', exc_info=True)
        return False
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)
        temp_db.unlink(missing_ok=True)
        fallback_db.unlink(missing_ok=True)

    record = {
        'migrated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'source_app_id': LEGACY_APP_ID,
        'target_app_id': APP_ID,
        'source_root': str(chosen_root),
        'target_root': str(data_root),
        'copied_folders': copied_folders,
        'copied_files': copied_files,
        'migrated_elevators': chosen_elevators,
    }
    record_tmp = checked_data_path(data_root, f'{MIGRATION_FILE}.{os.getpid()}.tmp')
    checked_data_path(data_root, MIGRATION_FILE)
    record_tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    record_tmp.replace(checked_data_path(data_root, MIGRATION_FILE))
    logging.info('已从 1.x 目录安全复制台账资料：%s -> %s（共 %s 个文件，%s 部电梯）',
                 chosen_root, data_root, copied_files, chosen_elevators)
    return True


def configure_logging(data_root):
    stream = open(checked_data_path(data_root, 'logs/launcher.log'), 'a', encoding='utf-8', buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    logging.basicConfig(stream=stream, level=logging.INFO, force=True,
                        format='%(asctime)s %(levelname)s %(message)s')


def check_installation(program_root, data_root=None):
    if os.name == 'nt' and (sys.version_info[:2] != (3, 12) or struct.calcsize('P') != 8):
        raise RuntimeError('运行环境需要安装包内的 Python 3.12 64位版本。')
    for name in ('fastapi', 'uvicorn', 'docx', 'PIL.Image', 'qrcode', 'multipart', 'openpyxl'):
        importlib.import_module(name)
    if os.name == 'nt':
        try:
            importlib.import_module('webview')
            importlib.import_module('clr')
        except Exception as exc:
            raise RuntimeError('无法加载桌面窗口组件。请检查 .NET Framework 并重新安装完整程序。') from exc
    with closing(sqlite3.connect(':memory:')) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('SQLite 运行环境检查失败。')
    if data_root is not None:
        existing = checked_data_path(data_root, 'data/elevator.db')
        if existing.is_file():
            with closing(sqlite3.connect(existing.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise RuntimeError('现有数据库检查失败，请保留数据并联系管理员恢复备份。')
    for relative in ('backend/main.py', 'backend/db.py', 'frontend/dist/index.html'):
        if not (program_root / relative).is_file():
            raise RuntimeError(f'程序文件缺失：{relative}。请重新安装，业务数据不会被安装程序删除。')
    page = (program_root / 'frontend/dist/index.html').read_text(encoding='utf-8')
    assets = re.findall(r'''(?:src|href)=["'](/assets/[^"'?]+)''', page)
    if not assets or any(not (program_root / 'frontend/dist' / name.lstrip('/')).is_file() for name in assets):
        raise RuntimeError('页面资源缺失，请重新安装完整程序。')


def try_lock(data_root):
    handle = open(checked_data_path(data_root, LOCK_FILE), 'a+b', buffering=0)
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            # The POSIX branch permits real lifecycle tests on the build host.
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            return None
        raise
    return handle


def load_state(data_root, port):
    path = checked_data_path(data_root, STATE_FILE)
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
        if state.get('app') == APP_ID and state.get('port') == port and re.fullmatch(r'[0-9a-f]{64}', state.get('secret', '')):
            return state
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def local_request(port, path, headers=None, method='GET', timeout=1):
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(f'http://127.0.0.1:{port}{path}', headers=headers or {}, method=method,
                      data=b'' if method == 'POST' else None)
    with opener.open(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError('本机实例尚未就绪。')
        return json.loads(response.read(4096))


def signature(secret, challenge):
    return hmac.new(bytes.fromhex(secret), challenge.encode('ascii'), hashlib.sha256).hexdigest()


def probe_instance(state):
    if not isinstance(state, dict) or state.get('app') != APP_ID:
        return False
    challenge = secrets.token_hex(32)
    try:
        result = local_request(state['port'], IDENTITY_PATH, {'X-Launcher-Challenge': challenge})
        proof = result.get('proof', '')
        if not isinstance(proof, str) or not secrets.compare_digest(proof, signature(state['secret'], challenge)):
            return False
        return result.get('app') == APP_ID and result.get('ready') is True and local_request(state['port'], '/api/health') == {'ok': True}
    except (OSError, ValueError, RuntimeError, TypeError, AttributeError):
        return False


class LocalControl:
    """Launcher-only ASGI routes; the public backend and its business routes are unchanged."""
    def __init__(self, app, secret, ready, stop):
        self.app, self.secret, self.ready, self.stop = app, secret, ready, stop

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['path'] not in (IDENTITY_PATH, STOP_PATH):
            return await self.app(scope, receive, send)
        headers = dict(scope['headers'])
        local = scope.get('client', ('', 0))[0] in ('127.0.0.1', '::1')
        status, result = 403, {'detail': '仅允许本机启动器操作。'}
        if local and b'origin' not in headers:
            challenge = headers.get(b'x-launcher-challenge', b'')
            if scope['path'] == IDENTITY_PATH and scope['method'] == 'GET' and re.fullmatch(b'[0-9a-f]{64}', challenge):
                status = 200 if self.ready() else 503
                result = {'app': APP_ID, 'ready': self.ready(), 'version': APP_VERSION,
                          'proof': signature(self.secret, challenge.decode('ascii'))}
            elif scope['path'] == STOP_PATH and scope['method'] == 'POST' and secrets.compare_digest(
                    headers.get(b'x-launcher-token', b''), self.secret.encode('ascii')):
                self.stop()
                status, result = 200, {'stopping': True}
        body = json.dumps(result, ensure_ascii=False).encode('utf-8')
        await send({'type': 'http.response.start', 'status': status,
                    'headers': [(b'content-type', b'application/json; charset=utf-8'), (b'cache-control', b'no-store')]})
        await send({'type': 'http.response.body', 'body': body})


def wait_existing(data_root, port, timeout=START_TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = load_state(data_root, port)
        if state and probe_instance(state):
            return state
        lock = try_lock(data_root)
        if lock:
            lock.close()
            break
        time.sleep(0.1)
    raise RuntimeError('现有电梯台账 2.0 实例尚未就绪或无法验证，请查看日志；不会连接旧版或其他占用端口的服务。')


def _candidate_stop_roots(data_root):
    roots = []
    if data_root is not None and data_root.is_dir():
        roots.append(data_root)
    if os.name == 'nt':
        profile = Path(os.environ.get('USERPROFILE', ''))
        users_dir = profile.parent if profile.is_absolute() else None
        if users_dir and _safe_legacy_entry(users_dir, directory=True):
            try:
                for entry in sorted(users_dir.iterdir(), key=lambda p: p.name):
                    candidate = entry / 'AppData' / 'Local' / APP_ID
                    if candidate not in roots and _safe_legacy_entry(candidate, directory=True):
                        roots.append(candidate)
            except OSError:
                pass
    return roots


def _stop_single_root(data_root, port, deadline):
    sent = False
    while time.monotonic() < deadline:
        lock = try_lock(data_root)
        if lock:
            lock.close()
            return
        if not sent:
            state = load_state(data_root, port)
            if state and probe_instance(state):
                result = local_request(port, STOP_PATH, {'X-Launcher-Token': state['secret']}, method='POST')
                if result != {'stopping': True}:
                    raise RuntimeError('停止请求未获确认，已取消操作。')
                sent = True
        time.sleep(0.1)
    raise RuntimeError('电梯台账未能在45秒内安全停止。请等待正在进行的操作完成后重试；程序不会强制结束进程。')


def stop_instance(data_root, port=PORT, timeout=STOP_TIMEOUT, *, scan_users=False):
    deadline = time.monotonic() + timeout
    roots = _candidate_stop_roots(data_root) if scan_users else [data_root]
    for root in roots:
        if root is not None and root.exists():
            _stop_single_root(root, port, deadline)


def activate_existing_window(pid, quiet=False):
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = wintypes.HWND
    hwnd = wintypes.HWND(user32.FindWindowW(None, WINDOW_TITLE))
    owner = wintypes.DWORD()
    if isinstance(pid, int) and pid > 0 and hwnd and user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner)) and owner.value == pid:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        if user32.SetForegroundWindow(hwnd):
            return
    if not quiet:
        user32.MessageBoxW(None, '电梯管理系统 2.0 已在运行。请切换到已打开的桌面窗口。', WINDOW_TITLE, 0x40)


def open_operator_window(program_root, url, stopped, data_root=None):
    import webview

    if data_root is not None:
        webview_dir = checked_data_path(data_root, 'WebView2', directory=True)
    elif os.environ.get('LOCALAPPDATA', ''):
        webview_dir = checked_data_path(resolve_data_root(program_root=program_root), 'WebView2', directory=True)
    else:
        configured_wv2 = os.environ.get('WEBVIEW2_USER_DATA_FOLDER', '')
        if not configured_wv2 or not Path(configured_wv2).is_absolute():
            raise RuntimeError('无法确定当前用户的本地数据目录（LOCALAPPDATA）。')
        webview_dir = Path(configured_wv2)
    resolved_program = Path(os.path.abspath(program_root))
    resolved_wv2 = Path(os.path.abspath(webview_dir))
    if resolved_wv2 == resolved_program or resolved_program in resolved_wv2.parents:
        raise RuntimeError(f'WebView2 缓存目录必须独立于程序安装目录：{webview_dir}')
    webview_dir.mkdir(parents=True, exist_ok=True)
    os.environ['WEBVIEW2_USER_DATA_FOLDER'] = str(webview_dir)

    if os.name == 'nt' and hasattr(ctypes, 'windll') and hasattr(ctypes.windll, 'shell32'):
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass

    icon = program_root / ICON_NAME
    if not icon.is_file():
        icon = program_root / 'scripts' / ICON_NAME
    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False
    window = webview.create_window(WINDOW_TITLE, url, width=1440, height=900, maximized=True, text_select=True)
    initialization_failed = threading.Event()

    def close_on_stop():
        stopped.wait()
        if not window.events.closed.is_set():
            window.destroy()

    def check_initialization(sender, args):
        if args.IsSuccess:
            # Keep Back, Find and Print available for ledger pages and opened photos.
            sender.CoreWebView2.Settings.AreBrowserAcceleratorKeysEnabled = True
            return
        logging.error('WebView2 初始化失败：%s', args.InitializationException)
        initialization_failed.set()
        stopped.set()

    def watch_initialization():
        window.native.webview.CoreWebView2InitializationCompleted += check_initialization

    # pywebview can select MSHTML when Edge is missing. Veto it before creating the form.
    window.events.initialized += lambda renderer: renderer == 'edgechromium'
    window.events.before_show += watch_initialization
    window.events.shown += close_on_stop
    try:
        webview.start(gui='edgechromium', icon=str(icon), private_mode=False, storage_path=str(webview_dir))
    except Exception as exc:
        raise RuntimeError(WEBVIEW2_ERROR) from exc
    if webview.renderer != 'edgechromium' or initialization_failed.is_set():
        raise RuntimeError(WEBVIEW2_ERROR)


def run_server(program_root, data_root, port=PORT, app=None, quiet=False, program_data=None):
    lock = try_lock(data_root)
    if not lock:
        state = wait_existing(data_root, port)
        activate_existing_window(state.get('pid'), quiet)
        return
    sock = None
    state = {'app': APP_ID, 'version': APP_VERSION, 'pid': os.getpid(), 'port': port, 'secret': secrets.token_hex(32)}
    stopped = threading.Event()
    try:
        if (program_root / 'maintenance.flag').exists() or checked_data_path(data_root, 'maintenance.flag').exists():
            raise RuntimeError('电梯台账正在安装或维护，请完成操作后再启动。')
        configure_seed_ledger(program_root)
        migrate_legacy_data(data_root, program_data=program_data)
        check_installation(program_root, data_root)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == 'nt':
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('0.0.0.0', port))
        except OSError as exc:
            raise RuntimeError(f'端口{port}已被其他程序占用。请先确认占用程序并正常关闭；电梯台账不会结束其他服务。') from exc
        temporary = checked_data_path(data_root, STATE_FILE + f'.{os.getpid()}.tmp')
        checked_data_path(data_root, STATE_FILE)
        temporary.write_text(json.dumps(state), encoding='utf-8')
        temporary.replace(checked_data_path(data_root, STATE_FILE))
        if app is None:
            sys.path.insert(0, str(program_root))
            from backend.main import app
        import uvicorn

        def request_stop():
            stopped.set()
            server.should_exit = True

        control = LocalControl(app, state['secret'], lambda: server.started, request_stop)
        server = uvicorn.Server(uvicorn.Config(control, host='0.0.0.0', port=port, proxy_headers=False,
                                              log_config=None, access_log=False, timeout_graceful_shutdown=None))

        logging.info('安装版 2.0 服务启动，端口%s，数据目录%s', port, data_root)
        with ThreadPoolExecutor(max_workers=1) as worker:
            host = worker.submit(server.run, sockets=[sock])
            host.add_done_callback(lambda _: stopped.set())
            try:
                deadline = time.monotonic() + START_TIMEOUT
                while not stopped.is_set():
                    if time.monotonic() >= deadline:
                        raise RuntimeError('电梯台账就绪检查超时，请查看日志。')
                    if probe_instance(state):
                        if not stopped.is_set():
                            os.environ['WEBVIEW2_USER_DATA_FOLDER'] = str(
                                checked_data_path(data_root, 'WebView2', directory=True)
                            )
                            open_operator_window(program_root, f'http://127.0.0.1:{port}', stopped)
                        break
                    stopped.wait(0.1)
            finally:
                request_stop()
            host.result()
            if not server.started:
                raise RuntimeError('电梯台账启动失败，请查看日志。')
    finally:
        if sock:
            sock.close()
        try:
            current = load_state(data_root, port)
            if current and current['secret'] == state['secret']:
                checked_data_path(data_root, STATE_FILE).unlink(missing_ok=True)
        finally:
            lock.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=WINDOW_TITLE)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--stop', action='store_true', help='安全停止本安装版 2.0 实例')
    actions.add_argument('--check', action='store_true', help='检查运行环境，不启动服务')
    actions.add_argument('--data-folder', action='store_true', help='打开当前用户的业务数据目录')
    parser.add_argument('--all-users', action='store_true', help='安装维护时检查并停止本机各账户下的 2.0 实例')
    parser.add_argument('--quiet', action='store_true', help='失败时仅记录日志并返回非零退出码')
    args = parser.parse_args(argv)
    data_root = None
    try:
        program_root = Path(__file__).resolve().parents[1]
        if args.check:
            # Elevated setup runs --check; never materialize a database or folders under the admin profile.
            local_base = Path(os.environ.get('LOCALAPPDATA', ''))
            existing_root = resolve_data_root(local_base, program_root=program_root) if (
                local_base.is_absolute() and (local_base / APP_ID).exists()
            ) else None
            check_installation(program_root, existing_root)
            return 0
        if args.stop and args.all_users:
            local_base = Path(os.environ.get('LOCALAPPDATA', ''))
            existing_root = resolve_data_root(local_base, program_root=program_root) if (
                local_base.is_absolute() and (local_base / APP_ID).exists()
            ) else None
            stop_instance(existing_root, scan_users=True)
            return 0
        data_root = configure_data_paths(program_root=program_root)
        configure_logging(data_root)
        if args.stop:
            stop_instance(data_root)
            if not args.quiet and os.name == 'nt':
                ctypes.windll.user32.MessageBoxW(None, '电梯管理系统 2.0 已停止。需要使用时请重新打开桌面图标。',
                                               WINDOW_TITLE, 0x40)
        elif args.data_folder:
            os.startfile(str(data_root))
        else:
            run_server(program_root, data_root, quiet=args.quiet)
        return 0
    except Exception as exc:
        logging.exception('安装版启动器失败')
        if not args.quiet and os.name == 'nt':
            log_path = f'{data_root}\\logs\\launcher.log' if data_root else f'%LOCALAPPDATA%\\{APP_ID}\\logs\\launcher.log'
            ctypes.windll.user32.MessageBoxW(None, f'{exc}\n\n详情见 {log_path}。',
                                           WINDOW_TITLE, 0x10)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

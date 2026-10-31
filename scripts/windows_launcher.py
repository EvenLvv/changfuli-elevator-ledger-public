"""Installed Windows entry point. Keep application files separate from shared business data."""
import argparse
import ctypes
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
import socket
import sqlite3
import stat
import struct
import sys
import threading
import time
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import webbrowser

APP_ID = 'ChangfuliElevatorLedger'
PORT = 8765
START_TIMEOUT = 45
STOP_TIMEOUT = 45
IDENTITY_PATH = '/_launcher/identity'
STOP_PATH = '/_launcher/stop'
STATE_FILE = 'runtime-instance.json'
LOCK_FILE = 'runtime-instance.lock'


def checked_data_path(data_root, relative, *, directory=False):
    path = data_root / relative
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
            expected_type = stat.S_ISDIR if is_directory else stat.S_ISREG
            if (stat.S_ISLNK(info.st_mode) or
                    getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT or
                    not expected_type(info.st_mode)):
                raise RuntimeError(f'公共数据路径包含链接、重解析点或类型不符：{current}。请联系管理员检查。')
    return path


def configure_data_paths(program_data=None):
    base = Path(program_data or os.environ.get('PROGRAMDATA', ''))
    if not base.is_absolute():
        raise RuntimeError('无法确定 Windows 公共数据目录（ProgramData）。')
    data_root = base / APP_ID
    for key, folder in [('DATA', 'data'), ('STORAGE', 'storage'), ('EXPORT', 'exports'),
                        ('BACKUP', 'backups'), ('LOG', 'logs')]:
        path = checked_data_path(data_root, folder, directory=True)
        path.mkdir(parents=True, exist_ok=True)
        checked_data_path(data_root, folder, directory=True)
        # Installed versions share this location; inherited overrides never select another database.
        os.environ[f'ELEVATOR_{key}_DIR'] = str(path)
    return data_root


def configure_logging(data_root):
    stream = open(checked_data_path(data_root, 'logs/launcher.log'), 'a', encoding='utf-8', buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    logging.basicConfig(stream=stream, level=logging.INFO, force=True,
                        format='%(asctime)s %(levelname)s %(message)s')


def check_installation(program_root, data_root):
    if os.name == 'nt' and (sys.version_info[:2] != (3, 12) or struct.calcsize('P') != 8):
        raise RuntimeError('运行环境需要安装包内的 Python 3.12 64位版本。')
    for name in ('fastapi', 'uvicorn', 'docx', 'PIL.Image', 'qrcode', 'multipart', 'openpyxl'):
        importlib.import_module(name)
    with sqlite3.connect(':memory:') as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('SQLite 运行环境检查失败。')
    existing = checked_data_path(data_root, 'data/elevator.db')
    if existing.is_file():
        with sqlite3.connect(existing.resolve().as_uri() + '?mode=ro', uri=True) as db:
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
                result = {'app': APP_ID, 'ready': self.ready(), 'proof': signature(self.secret, challenge.decode('ascii'))}
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
    raise RuntimeError('现有电梯台账实例尚未就绪或无法验证，请查看日志；不会打开其他占用端口的服务。')


def stop_instance(data_root, port=PORT, timeout=STOP_TIMEOUT):
    deadline = time.monotonic() + timeout
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


def run_server(program_root, data_root, port=PORT, open_browser=True, app=None):
    lock = try_lock(data_root)
    if not lock:
        wait_existing(data_root, port)
        if open_browser:
            webbrowser.open(f'http://127.0.0.1:{port}')
        return
    sock = None
    state = {'app': APP_ID, 'port': port, 'secret': secrets.token_hex(32)}
    cancel, ready, stopped = threading.Event(), threading.Event(), threading.Event()
    try:
        if checked_data_path(data_root, 'maintenance.flag').exists():
            raise RuntimeError('电梯台账正在安装或维护，请完成操作后再启动。')
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

        def browser_when_ready():
            deadline = time.monotonic() + START_TIMEOUT
            while not cancel.is_set() and time.monotonic() < deadline:
                if probe_instance(state):
                    ready.set()
                    if open_browser and not stopped.is_set():
                        webbrowser.open(f'http://127.0.0.1:{port}')
                    return
                cancel.wait(0.1)
            if not cancel.is_set():
                server.should_exit = True

        watcher = threading.Thread(target=browser_when_ready, daemon=True)
        watcher.start()
        logging.info('安装版服务启动，端口%s，数据目录%s', port, data_root)
        try:
            server.run(sockets=[sock])
        finally:
            cancel.set()
            watcher.join(timeout=3)
        if not ready.is_set() and not stopped.is_set():
            raise RuntimeError('电梯台账启动失败或就绪检查超时，请查看日志。')
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
    parser = argparse.ArgumentParser(description='昌福里社区27区电梯管理台账')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--stop', action='store_true', help='安全停止本安装版实例')
    actions.add_argument('--check', action='store_true', help='检查运行环境，不启动服务')
    actions.add_argument('--data-folder', action='store_true', help='打开公共业务数据目录')
    parser.add_argument('--quiet', action='store_true', help='失败时仅记录日志并返回非零退出码')
    args = parser.parse_args(argv)
    try:
        data_root = configure_data_paths()
        configure_logging(data_root)
        program_root = Path(__file__).resolve().parents[1]
        if args.stop:
            stop_instance(data_root)
            if not args.quiet and os.name == 'nt':
                ctypes.windll.user32.MessageBoxW(None, '电梯管理系统已停止。需要使用时请重新打开桌面图标。',
                                               '昌福里社区27区电梯管理台账', 0x40)
        elif args.data_folder:
            os.startfile(str(data_root))
        elif args.check:
            check_installation(program_root, data_root)
            logging.info('安装版运行环境检查通过')
        else:
            run_server(program_root, data_root)
        return 0
    except Exception as exc:
        logging.exception('安装版启动器失败')
        if not args.quiet and os.name == 'nt':
            ctypes.windll.user32.MessageBoxW(None, str(exc) + '\n\n详情见 ProgramData\\ChangfuliElevatorLedger\\logs\\launcher.log。',
                                           '昌福里社区27区电梯管理台账', 0x10)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

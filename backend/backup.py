import json
import sqlite3
import threading
import zipfile
from datetime import datetime

from .db import BACKUPS, COMMUNITY, DB, STORAGE, now

# ponytail: serialize backups on this single-server deployment to keep retention predictable.
_backup_lock = threading.Lock()


def create_backup():
    with _backup_lock:
        timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S_%f')
        target = BACKUPS / f'backup_{timestamp}.zip'
        partial = target.with_suffix('.partial')
        snapshot = BACKUPS / f'snapshot_{timestamp}.db'
        try:
            source = sqlite3.connect(DB)
            copy = sqlite3.connect(snapshot)
            try:
                source.backup(copy)
                copy.execute('DELETE FROM sessions')
                copy.commit()
                copy.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                copy.execute('PRAGMA journal_mode=DELETE')
                referenced = copy.execute('SELECT original_name,relative_path FROM attachments').fetchall()
            finally:
                copy.close()
                source.close()
            for name, relative in referenced:
                path = (STORAGE / relative).resolve()
                if not path.is_relative_to(STORAGE.resolve()) or not path.is_file():
                    raise ValueError(f'附件缺失，备份未完成：{name}')
            with zipfile.ZipFile(partial, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.write(snapshot, 'data/elevator.db')
                for path in STORAGE.rglob('*'):
                    if path.is_file() and path.resolve().is_relative_to(STORAGE.resolve()):
                        archive.write(path, 'storage/' + path.relative_to(STORAGE).as_posix())
                archive.writestr('backup_info.json', json.dumps({'created_at': now(), 'format': 1,
                    'community': COMMUNITY, 'settings': '数据库 system_settings 表',
                    'sessions': '恢复后需重新登录'}, ensure_ascii=False))
            partial.replace(target)
        finally:
            snapshot.unlink(missing_ok=True)
            for suffix in ('-wal', '-shm'):
                snapshot.with_name(snapshot.name + suffix).unlink(missing_ok=True)
            partial.unlink(missing_ok=True)
        for old in sorted(BACKUPS.glob('backup_*.zip'), reverse=True)[30:]:
            old.unlink(missing_ok=True)
        return target

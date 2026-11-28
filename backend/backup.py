import json
import sqlite3
import threading
import zipfile
from datetime import datetime

from .db import BACKUPS, COMMUNITY, DB, STORAGE, SHANGHAI, now
from .drafts import DRAFT_PHOTO_FOLDER, draft_photo_path

# ponytail: serialize backups on this single-server deployment to keep retention predictable.
_backup_lock = threading.Lock()


def create_backup():
    with _backup_lock:
        timestamp = datetime.now(SHANGHAI).strftime('%Y-%m-%d_%H%M%S_%f')
        target = BACKUPS / f'backup_{timestamp}.zip'
        partial = target.with_suffix('.partial')
        snapshot = BACKUPS / f'snapshot_{timestamp}.db'
        try:
            source = sqlite3.connect(DB)
            copy = sqlite3.connect(snapshot)
            try:
                source.backup(copy)
                copy.row_factory = sqlite3.Row
                copy.execute('DELETE FROM sessions')
                copy.commit()
                copy.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                copy.execute('PRAGMA journal_mode=DELETE')
                referenced = copy.execute('SELECT original_name,relative_path FROM attachments').fetchall()
                has_draft_photos = copy.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='draft_photos'").fetchone()
                draft_photos = copy.execute('SELECT original_name,relative_path,size FROM draft_photos').fetchall() if has_draft_photos else ()
            finally:
                copy.close()
                source.close()
            for name, relative in referenced:
                path = (STORAGE / relative).resolve()
                if not path.is_relative_to(STORAGE.resolve()) or not path.is_file():
                    raise ValueError(f'附件缺失，备份未完成：{name}')
            draft_paths = []
            for photo in draft_photos:
                path = draft_photo_path(photo)
                if path is None:
                    raise ValueError(f"文稿原图缺失或文件无效，备份未完成：{photo['original_name']}")
                draft_paths.append((path, photo['relative_path']))
            with zipfile.ZipFile(partial, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.write(snapshot, 'data/elevator.db')
                for folder in STORAGE.iterdir():
                    if folder.name == DRAFT_PHOTO_FOLDER:
                        continue
                    for path in folder.rglob('*') if folder.is_dir() else (folder,):
                        if path.is_file() and path.resolve().is_relative_to(STORAGE.resolve()):
                            archive.write(path, 'storage/' + path.relative_to(STORAGE).as_posix())
                # The snapshot determines which draft photos are committed, even if a save is in progress.
                for path, relative in draft_paths:
                    archive.write(path, 'storage/' + relative)
                archive.writestr('backup_info.json', json.dumps({'created_at': now(), 'format': 1,
                    'community': COMMUNITY, 'settings': '数据库 system_settings 表',
                    'access': '恢复后可直接打开台账'}, ensure_ascii=False))
            partial.replace(target)
        finally:
            snapshot.unlink(missing_ok=True)
            for suffix in ('-wal', '-shm'):
                snapshot.with_name(snapshot.name + suffix).unlink(missing_ok=True)
            partial.unlink(missing_ok=True)
        for old in sorted(BACKUPS.glob('backup_*.zip'), reverse=True)[30:]:
            old.unlink(missing_ok=True)
        return target

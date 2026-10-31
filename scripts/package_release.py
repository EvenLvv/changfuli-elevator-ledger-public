"""Package source, built pages and offline dependencies; never include live data."""
import hashlib
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parents[1]
target = root / '昌福里社区27区党群物业服务站_电梯管理台账_1.0_源码与页面.zip'
prefix = 'elevator-management/'
files = set(root.glob('*.md')) | set(root.glob('*.bat')) | set(root.glob('requirements*.txt'))
for folder in ('backend', 'scripts', 'tests', 'docs', 'wheelhouse', 'frontend'):
    files.update(p for p in (root / folder).rglob('*') if p.is_file()
                 and not {'node_modules', '__pycache__', '.pytest_cache'}.intersection(p.parts)
                 and p.suffix != '.pyc')
assert (root / 'frontend/dist/index.html') in files
assert len(list((root / 'wheelhouse').glob('*.whl'))) >= 25
partial = target.with_suffix('.partial')
with ZipFile(partial, 'w', ZIP_DEFLATED) as archive:
    for path in sorted(files):
        archive.write(path, prefix + path.relative_to(root).as_posix())
    for folder in ('data', 'storage/photos', 'storage/attachments', 'exports', 'backups', 'logs'):
        archive.writestr(prefix + folder + '/.gitkeep', '')
with ZipFile(partial) as archive:
    assert archive.testzip() is None
    assert prefix + '启动电梯管理系统.bat' in archive.namelist()
    assert not any(name.endswith(('.db', '.db-wal', '.db-shm', '.log')) for name in archive.namelist())
partial.replace(target)
digest = hashlib.sha256(target.read_bytes()).hexdigest()
target.with_suffix('.zip.sha256').write_text(digest + '  ' + target.name + '\n', encoding='utf-8')
print(f'{target.name}: {len(files)} files, {target.stat().st_size:,} bytes\nSHA256: {digest}')

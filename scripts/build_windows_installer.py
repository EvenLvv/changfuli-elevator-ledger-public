"""Build a self-contained Windows installer from pinned, local inputs only."""
from __future__ import annotations

import argparse
import email
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
APP_ID = 'ChangfuliElevatorLedger'
PYTHON_VERSION = '3.12.10'
PYTHON_SHA256 = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'
PTH_CONTENT = 'python312.zip\n.\nLib/site-packages\n..\nimport site\n'
OWNED_DIRECTORIES = ('backend', 'frontend', 'scripts', 'runtime', 'docs', 'licenses')


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else hashlib.sha256(stream.read()).hexdigest()


def validate_zip(archive):
    seen = set()
    for item in archive.infolist():
        name = item.filename
        pure = PurePosixPath(name)
        if '\\' in name or ':' in name or pure.is_absolute() or '..' in pure.parts or not pure.parts:
            raise ValueError(f'Unsafe archive path: {name}')
        if stat.S_ISLNK(item.external_attr >> 16):
            raise ValueError(f'Symlinks are not allowed in build inputs: {name}')
        key = name.casefold()
        if key in seen:
            raise ValueError(f'Duplicate archive path: {name}')
        seen.add(key)
    if archive.testzip() is not None:
        raise ValueError('Archive failed its CRC check')


def locked_requirements(path):
    requirements = {}
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)', line)
        if not match:
            raise ValueError(f'Only exact package pins are accepted: {line}')
        name = re.sub(r'[-_.]+', '-', match[1]).lower()
        if name in requirements:
            raise ValueError(f'Duplicate package pin: {name}')
        requirements[name] = match[2]
    if not requirements:
        raise ValueError('The dependency lock file is empty')
    return requirements


def selected_wheels(wheelhouse, requirements):
    selected = {}
    for wheel in sorted(wheelhouse.glob('*.whl')):
        with ZipFile(wheel) as archive:
            validate_zip(archive)
            metadata_files = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA') and n.count('/') == 1]
            if len(metadata_files) != 1:
                raise ValueError(f'Invalid wheel metadata: {wheel.name}')
            metadata = email.message_from_bytes(archive.read(metadata_files[0]))
        name = re.sub(r'[-_.]+', '-', metadata['Name'] or '').lower()
        if name not in requirements or metadata['Version'] != requirements[name]:
            continue
        if not re.search(r'-(?:py3|py2\.py3)-none-any\.whl$|-cp312-cp312-win_amd64\.whl$', wheel.name):
            raise ValueError(f'Expected a Python 3.12 Windows x64 or pure Python wheel: {wheel.name}')
        if name in selected:
            raise ValueError(f'Multiple matching wheels for {name}; use a clean wheelhouse')
        selected[name] = wheel
    missing = set(requirements) - set(selected)
    if missing:
        raise ValueError('Missing pinned wheels: ' + ', '.join(sorted(missing)))
    return [selected[name] for name in sorted(selected)]


def copy_file(source, destination):
    if not source.is_file() or source.is_symlink():
        raise ValueError(f'Missing or unsafe application file: {source}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def copy_tree(source, destination):
    if not source.is_dir() or source.is_symlink():
        raise ValueError(f'Missing or unsafe application directory: {source}')
    for path in sorted(source.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Application symlinks cannot enter the installer: {path}')
        if path.is_file():
            copy_file(path, destination / path.relative_to(source))


def collect_licenses(stage):
    target = stage / 'licenses'
    target.mkdir()
    copy_file(stage / 'runtime/LICENSE.txt', target / 'Python-LICENSE.txt')
    lines = [f'Python {PYTHON_VERSION}: Python-LICENSE.txt', '', 'Third-party package licenses are also retained in runtime/Lib/site-packages/*.dist-info/.', '']
    for info in sorted((stage / 'runtime/Lib/site-packages').glob('*.dist-info')):
        metadata = email.message_from_bytes((info / 'METADATA').read_bytes())
        lines.append(f"{metadata['Name']}=={metadata['Version']}")
        for file in sorted(info.rglob('*')):
            if file.is_file() and re.match(r'(license|licence|copying|notice|authors)', file.name, re.I):
                relative = Path(info.name) / file.relative_to(info)
                copy_file(file, target / relative)
                lines.append('  ' + relative.as_posix())
        lines.append('')
    (target / 'THIRD_PARTY_LICENSES.txt').write_text('\n'.join(lines), encoding='utf-8')


def stage_application(python_zip, wheelhouse, output_dir, version):
    if sha256(python_zip) != PYTHON_SHA256:
        raise ValueError('The Python ZIP SHA256 does not match the official Python 3.12.10 x64 input')
    lock = ROOT / 'requirements.lock.txt'
    wheels = selected_wheels(wheelhouse, locked_requirements(lock))
    for required in ('scripts/windows_launcher.py', 'frontend/dist/index.html', 'scripts/windows-app.ico', 'docs/WINDOWS_INSTALLER.md'):
        if not (ROOT / required).is_file():
            raise ValueError(f'Build prerequisite missing: {required}')
    stage = Path(tempfile.mkdtemp(prefix='.stage-', dir=output_dir))
    try:
        runtime = stage / 'runtime'
        runtime.mkdir()
        with ZipFile(python_zip) as archive:
            validate_zip(archive)
            for required in ('python.exe', 'pythonw.exe', 'python312.dll', 'python312.zip', 'python312._pth', 'LICENSE.txt'):
                if required not in archive.namelist():
                    raise ValueError(f'The embedded Python runtime lacks {required}')
            archive.extractall(runtime)
        (runtime / 'python312._pth').write_text(PTH_CONTENT, encoding='ascii')
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-index',
                        '--find-links', str(wheelhouse), '--target', str(runtime / 'Lib/site-packages'),
                        '--platform', 'win_amd64', '--python-version', '3.12', '--implementation', 'cp', '--abi', 'cp312',
                        '--only-binary=:all:', '--no-deps', '--no-compile', '--no-warn-script-location', '-r', str(lock)], check=True)
        # The launcher uses modules directly; host-generated console scripts must not ship.
        for name in ('bin', 'Scripts'):
            shutil.rmtree(runtime / 'Lib/site-packages' / name, ignore_errors=True)
        for source in sorted((ROOT / 'backend').glob('*.py')):
            copy_file(source, stage / 'backend' / source.name)
        copy_file(ROOT / 'scripts/windows_launcher.py', stage / 'scripts/windows_launcher.py')
        copy_tree(ROOT / 'frontend/dist', stage / 'frontend/dist')
        copy_file(ROOT / 'scripts/windows-app.ico', stage / 'windows-app.ico')
        copy_file(lock, stage / 'requirements.lock.txt')
        copy_file(ROOT / 'docs/WINDOWS_INSTALLER.md', stage / 'docs/安装使用说明.txt')
        copy_file(ROOT / 'USER_GUIDE.md', stage / 'docs/USER_GUIDE.md')
        collect_licenses(stage)
        for path in stage.rglob('*'):
            if path.is_file() and path.suffix.lower() in ('.db', '.sqlite', '.sqlite3', '.log', '.pyc'):
                raise ValueError(f'Runtime data or compiled host files entered staging: {path}')
        manifest = {'product': APP_ID, 'version': version, 'python_version': PYTHON_VERSION,
                    'python_zip_sha256': PYTHON_SHA256, 'requirements_sha256': sha256(lock),
                    'wheels': {wheel.name: sha256(wheel) for wheel in wheels},
                    'files': {path.relative_to(stage).as_posix(): sha256(path) for path in sorted(stage.rglob('*')) if path.is_file()}}
        (stage / 'BUILD-MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        epoch = int(os.environ.get('SOURCE_DATE_EPOCH', '1744070400'))
        for path in stage.rglob('*'):
            os.utime(path, (epoch, epoch))
        target = output_dir / 'stage'
        if target.exists():
            marker = target / 'BUILD-MANIFEST.json'
            if target.is_symlink() or not marker.is_file() or json.loads(marker.read_text(encoding='utf-8')).get('product') != APP_ID:
                raise ValueError(f'Refusing to replace a staging directory not owned by this builder: {target}')
            shutil.rmtree(target)
        stage.rename(target)
        return target
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-zip', type=Path, required=True, help='Official python-3.12.10-embed-amd64.zip')
    parser.add_argument('--wheelhouse', type=Path, default=ROOT / 'wheelhouse')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs/windows-installer')
    parser.add_argument('--version', default='1.0.0')
    parser.add_argument('--makensis', default=shutil.which('makensis'))
    parser.add_argument('--stage-only', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'\d{1,5}\.\d{1,5}\.\d{1,5}', args.version) or any(int(part) > 65535 for part in args.version.split('.')):
        parser.error('--version must contain three numeric components from 0 to 65535')
    if not args.stage_only and not args.makensis:
        parser.error('NSIS makensis was not found; install NSIS or pass --makensis')
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stage = stage_application(args.python_zip.resolve(), args.wheelhouse.resolve(), output_dir, args.version)
    if args.stage_only:
        print(stage)
        return
    filename = f'{APP_ID}-Setup-{args.version}-x64.exe'
    target, partial = output_dir / filename, output_dir / (filename + '.partial')
    payload_kb = (sum(path.stat().st_size for path in stage.rglob('*') if path.is_file()) + 1023) // 1024
    try:
        subprocess.run([str(args.makensis), '-V3', f'-DSTAGE_DIR={stage}', f'-DOUT_FILE={partial}',
                        f'-DAPP_VERSION={args.version}', f'-DPAYLOAD_KB={payload_kb}', str(ROOT / 'scripts/windows_installer.nsi')], check=True)
        if not partial.is_file() or partial.read_bytes()[:2] != b'MZ':
            raise ValueError('NSIS did not produce a Windows executable')
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    digest = sha256(target)
    target.with_suffix('.exe.sha256').write_text(f'{digest}  {target.name}\n', encoding='ascii')
    print(f'Installer: {target}\nSHA256: {digest}\nPayload: {stage}')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'Build failed: {exc}', file=sys.stderr)
        raise SystemExit(1)

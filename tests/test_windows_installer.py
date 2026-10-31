"""Build-input, staging and NSIS compilation checks; no live business data is used."""
import importlib.util
import json
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('windows_installer_builder', ROOT / 'scripts/build_windows_installer.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class WindowsInstallerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def wheel(self, name='demo-1.0-py3-none-any.whl'):
        path = self.root / name
        with ZipFile(path, 'w') as archive:
            archive.writestr('demo-1.0.dist-info/METADATA', 'Name: demo\nVersion: 1.0\n')
            archive.writestr('demo.py', 'VALUE = 1\n')
        return path

    def test_archives_reject_traversal_and_symlinks(self):
        for name in ('../outside', '/outside', 'C:/outside', 'folder\\outside'):
            path = self.root / 'bad.zip'
            with ZipFile(path, 'w') as archive:
                archive.writestr(name, 'bad')
            with ZipFile(path) as archive, self.assertRaises(ValueError):
                builder.validate_zip(archive)
        path = self.root / 'symlink.zip'
        with ZipFile(path, 'w') as archive:
            info = ZipInfo('unsafe-link')
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, '/outside')
        with ZipFile(path) as archive, self.assertRaises(ValueError):
            builder.validate_zip(archive)

    def test_lock_and_wheels_require_exact_compatible_inputs(self):
        lock = self.root / 'requirements.lock.txt'
        lock.write_text('demo==1.0\n', encoding='utf-8')
        expected = builder.locked_requirements(lock)
        with self.assertRaises(ValueError):
            builder.selected_wheels(self.root, expected)
        wheel = self.wheel()
        self.assertEqual(builder.selected_wheels(self.root, expected), [wheel])
        wheel.rename(self.root / 'demo-1.0-cp312-cp312-macosx_11_0_arm64.whl')
        with self.assertRaises(ValueError):
            builder.selected_wheels(self.root, expected)
        lock.write_text('demo>=1\n--extra-index-url https://invalid.example\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            builder.locked_requirements(lock)

    def test_wrong_python_hash_and_source_symlinks_are_rejected(self):
        runtime = self.root / 'untrusted-runtime.zip'
        runtime.write_bytes(b'untrusted input')
        output = self.root / 'output'; output.mkdir()
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            builder.stage_application(runtime, self.root, output, '1.0.0')
        self.assertEqual(list(output.iterdir()), [])
        source = self.root / 'outside.txt'; source.write_text('must not be copied')
        link = self.root / 'link.txt'
        try:
            link.symlink_to(source)
        except OSError:
            self.skipTest('Host does not permit test symlinks')
        with self.assertRaises(ValueError):
            builder.copy_file(link, output / 'copied.txt')
        self.assertFalse((output / 'copied.txt').exists())

    def test_staging_uses_explicit_program_files_and_refuses_foreign_stage(self):
        source, output = self.root / 'project', self.root / 'output'
        source.mkdir(); output.mkdir()
        fixtures = {'requirements.lock.txt': 'demo==1.0\n', 'backend/__init__.py': '',
                    'backend/main.py': 'VALUE=1\n', 'backend/__pycache__/leak.pyc': 'do not ship',
                    'data/elevator.db': 'business data must never ship', 'scripts/windows_launcher.py': 'pass\n',
                    'scripts/windows-app.ico': 'fake test icon', 'frontend/dist/index.html': '<html></html>',
                    'docs/WINDOWS_INSTALLER.md': 'test instructions', 'USER_GUIDE.md': 'test guide'}
        for name, value in fixtures.items():
            target = source / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(value, encoding='utf-8')
        python_zip = self.root / 'python.zip'
        with ZipFile(python_zip, 'w') as archive:
            for name in ('python.exe', 'pythonw.exe', 'python312.dll', 'python312.zip', 'python312._pth', 'LICENSE.txt'):
                archive.writestr(name, 'runtime fixture')
        self.wheel()

        def install(arguments, **kwargs):
            self.assertIn('--no-index', arguments)
            self.assertIn('--no-deps', arguments)
            self.assertEqual(arguments[arguments.index('--platform') + 1], 'win_amd64')
            packages = Path(arguments[arguments.index('--target') + 1])
            info = packages / 'demo-1.0.dist-info'; info.mkdir(parents=True)
            (info / 'METADATA').write_text('Name: demo\nVersion: 1.0\n', encoding='utf-8')
            (info / 'LICENSE').write_text('fixture license', encoding='utf-8')
            (packages / 'demo.py').write_text('VALUE=1', encoding='utf-8')

        with patch.object(builder, 'ROOT', source), patch.object(builder, 'PYTHON_SHA256', builder.sha256(python_zip)), patch.object(builder.subprocess, 'run', install):
            stage = builder.stage_application(python_zip, self.root, output, '1.0.0')
            self.assertEqual((stage / 'runtime/python312._pth').read_text(), builder.PTH_CONTENT)
            self.assertFalse((stage / 'data').exists())
            self.assertFalse((stage / 'backend/__pycache__').exists())
            self.assertFalse((stage / 'tests').exists())
            manifest = json.loads((stage / 'BUILD-MANIFEST.json').read_text())
            self.assertEqual(manifest['product'], builder.APP_ID)
            for name, digest in manifest['files'].items():
                self.assertEqual(builder.sha256(stage / name), digest)
            self.assertTrue((stage / 'licenses/demo-1.0.dist-info/LICENSE').is_file())
            (stage / 'BUILD-MANIFEST.json').unlink()
            with self.assertRaises(ValueError):
                builder.stage_application(python_zip, self.root, output, '1.0.0')
            self.assertTrue((stage / 'backend/main.py').is_file())

    def test_maintenance_marker_uses_a_validated_handle_without_truncation(self):
        text = (ROOT / 'scripts/windows_installer.nsi').read_text(encoding='utf-8')
        maintenance = text.split('!macro MaintenanceFunctions PREFIX', 1)[1].split('!macroend', 1)[0]
        calls = [line.strip() for line in maintenance.splitlines() if 'kernel32::CreateFileW(' in line]
        self.assertEqual(len(calls), 2)
        # DELETE | FILE_READ_ATTRIBUTES, no delete sharing, CREATE_NEW then OPEN_EXISTING.
        self.assertIn('i 0x10080, i 3, p 0, i 1, i 0x02200080', calls[0])
        self.assertIn('i 0x10080, i 3, p 0, i 3, i 0x02200080', calls[1])
        self.assertIn('GetFileInformationByHandleEx(p $MaintenanceHandle, i 9', maintenance)
        self.assertIn('IntOp $2 $2 & 0x410', maintenance)
        self.assertIn('SetFileInformationByHandle(p $MaintenanceHandle, i 4', maintenance)
        self.assertNotIn('FileOpen ', maintenance)
        self.assertNotIn('FileWrite ', maintenance)
        self.assertNotIn('Delete "', maintenance)

    @unittest.skipUnless(shutil.which('makensis'), 'NSIS is not installed on this host')
    def test_nsis_compiles_and_has_narrow_data_safe_removal(self):
        source = ROOT / 'scripts/windows_installer.nsi'
        text = source.read_text(encoding='utf-8')
        removals = [line.strip() for line in text.splitlines() if line.strip().startswith('RMDir /r')]
        self.assertEqual(set(removals), {f'RMDir /r "$INSTDIR\\{name}"' for name in builder.OWNED_DIRECTORIES})
        self.assertIn('RequestExecutionLevel admin', text)
        self.assertIn('profile=private remoteip=localsubnet', text)
        self.assertIn('Call BeginMaintenance\n  Call StopCandidate', text)
        self.assertIn('Global\\${APP_ID}.Installer', text)
        self.assertIn('Call un.AcquireInstallerMutex', text)
        self.assertIn('Call ValidateDataRoot\n  DetailPrint', text)
        self.assertNotIn(' /T /C', text)
        stage = self.root / 'payload'; stage.mkdir(); (stage / 'fixture.txt').write_text('fixture')
        target = self.root / 'fixture-installer.exe'
        subprocess.run([shutil.which('makensis'), '-V2', f'-DSTAGE_DIR={stage}', f'-DOUT_FILE={target}', str(source)], check=True)
        self.assertEqual(target.read_bytes()[:2], b'MZ')


if __name__ == '__main__':
    unittest.main()

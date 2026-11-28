"""Build-input, staging, 2.0 identity, directory selection and NSIS compilation checks; no live business data is used."""
import importlib.util
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

from PIL import Image

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
        wheel = wheel.rename(self.root / 'demo-1.0-cp311.cp312.cp313-none-any.whl')
        self.assertEqual(builder.selected_wheels(self.root, expected), [wheel])
        wheel = wheel.rename(self.root / 'demo-1.0-cp311.cp313-none-any.whl')
        with self.assertRaises(ValueError):
            builder.selected_wheels(self.root, expected)
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
            builder.stage_application(runtime, self.root, output, '2.0.1')
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
        self.assertEqual(builder.APP_ID, 'ChangfuliElevatorDesktop')
        self.assertNotEqual(builder.APP_ID, 'ChangfuliElevatorLedger')
        source, output = self.root / 'project', self.root / 'output'
        source.mkdir(); output.mkdir()
        fixtures = {
            'requirements.lock.txt': 'demo==1.0\n',
            'backend/__init__.py': '',
            'backend/main.py': 'VALUE=1\n',
            'backend/__pycache__/leak.pyc': 'do not ship',
            'data/elevator.db': 'business data must never ship',
            'scripts/windows_launcher.py': 'pass\n',
            f'scripts/{builder.APP_ICON_ICO}': 'fake test ico',
            f'scripts/{builder.APP_ICON_PNG}': 'fake test png',
            'frontend/dist/index.html': '<html></html>',
            'docs/WINDOWS_INSTALLER.md': 'test instructions',
            'USER_GUIDE.md': 'test guide',
        }
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
            stage = builder.stage_application(python_zip, self.root, output, '2.0.1')
            self.assertEqual((stage / 'runtime/python312._pth').read_text(), builder.PTH_CONTENT)
            self.assertFalse((stage / 'data').exists())
            self.assertFalse((stage / 'backend/__pycache__').exists())
            self.assertFalse((stage / 'tests').exists())
            self.assertTrue((stage / builder.APP_ICON_ICO).is_file())
            self.assertTrue((stage / builder.APP_ICON_PNG).is_file())
            manifest = json.loads((stage / 'BUILD-MANIFEST.json').read_text())
            self.assertEqual(manifest['product'], 'ChangfuliElevatorDesktop')
            self.assertEqual(manifest['version'], '2.0.1')
            for name, digest in manifest['files'].items():
                self.assertEqual(builder.sha256(stage / name), digest)
            self.assertTrue((stage / 'licenses/demo-1.0.dist-info/LICENSE').is_file())
            self.assertFalse(list(stage.rglob('*.xlsx')))
            fixture = ROOT / 'tests/fixtures/synthetic-ledger-fixture.xlsx'
            stage = builder.stage_application(python_zip, self.root, output, '2.0.1', seed_ledger=fixture)
            manifest = json.loads((stage / 'BUILD-MANIFEST.json').read_text())
            self.assertEqual(manifest['files']['seed/official-ledger.xlsx'], builder.sha256(fixture))
            self.assertEqual((stage / 'seed/official-ledger.xlsx').read_bytes(), fixture.read_bytes())
            (stage / 'BUILD-MANIFEST.json').unlink()
            with self.assertRaises(ValueError):
                builder.stage_application(python_zip, self.root, output, '2.0.1')
            self.assertTrue((stage / 'backend/main.py').is_file())

    def test_new_brand_icons_are_multisize_emblem_and_home_hero_remains_lobby_photo(self):
        ico_path = ROOT / 'scripts/desktop-app-2.0.ico'
        png_path = ROOT / 'scripts/desktop-app-2.0.png'
        web_png_path = ROOT / 'frontend/src/assets/desktop-app-2.0.png'
        self.assertTrue(ico_path.is_file())
        self.assertTrue(png_path.is_file())
        self.assertTrue(web_png_path.is_file())
        with Image.open(ico_path) as ico:
            self.assertEqual(ico.format, 'ICO')
            self.assertTrue({(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}.issubset(ico.info.get('sizes', set())))
        for icon_file in (png_path, web_png_path):
            with Image.open(icon_file) as png:
                self.assertEqual(png.format, 'PNG')
                self.assertEqual(png.mode, 'RGBA')
                self.assertGreaterEqual(png.size[0], 256)
                self.assertEqual(png.size[0], png.size[1])
                w, h = png.size
                # Rounded plaque cropped tightly: corners are transparent, edge midpoints are opaque plaque.
                self.assertEqual(png.getpixel((0, 0))[3], 0)
                self.assertEqual(png.getpixel((w // 2, 2))[3], 255)
                self.assertEqual(png.getpixel((2, h // 2))[3], 255)
                # Center is warm elevator door light gap (not the retired flat cobalt #435ddd tile).
                center = png.getpixel((w // 2, h // 2))
                self.assertGreater(center[0], center[2])
                self.assertNotEqual(center[:3], (67, 93, 221))
                # Rich stone/steel emblem rather than a 2-3 color flat vector tile.
                sampled = {png.getpixel((x, h // 2))[:3] for x in range(10, w - 10, 4)}
                self.assertGreater(len(sampled), 40)
        self.assertNotEqual(ico_path.read_bytes(), (ROOT / 'scripts/windows-app.ico').read_bytes())
        index_html = (ROOT / 'frontend/index.html').read_text(encoding='utf-8')
        self.assertIn('/src/assets/desktop-app-2.0.png', index_html)
        self.assertIn('2.0.1', index_html)
        app_vue = (ROOT / 'frontend/src/App.vue').read_text(encoding='utf-8')
        self.assertIn("./assets/elevator-lobby.jpg", app_vue)
        self.assertNotIn('architecture.svg', app_vue)

    def test_nsis_directory_page_honors_user_choice_and_separates_2_0_identity(self):
        text = (ROOT / 'scripts/windows_installer.nsi').read_text(encoding='utf-8')
        uncommented = [
            line.strip() for line in text.splitlines()
            if line.strip() and not line.strip().startswith(';')
        ]
        # Directory selection page must appear between welcome and instfiles.
        welcome_idx = uncommented.index('!insertmacro MUI_PAGE_WELCOME')
        dir_idx = uncommented.index('!insertmacro MUI_PAGE_DIRECTORY')
        inst_idx = uncommented.index('!insertmacro MUI_PAGE_INSTFILES')
        self.assertLess(welcome_idx, dir_idx)
        self.assertLess(dir_idx, inst_idx)

        # Default InstallDir and 2.0-only InstallDirRegKey are present; never force INSTDIR back to ProgramFiles.
        self.assertIn('InstallDir "$PROGRAMFILES64\\${APP_ID}"', uncommented)
        self.assertIn('InstallDirRegKey HKLM "${UNINSTALL_KEY}" "InstallLocation"', uncommented)
        instdir_assignments = [line for line in uncommented if re.match(r'^StrCpy\s+\$INSTDIR\b', line, re.I)]
        self.assertEqual(instdir_assignments, ['StrCpy $INSTDIR $0'])
        for line in uncommented:
            self.assertIsNone(
                re.match(r'^StrCpy\s+\$(?:INSTDIR|0)\s+"\$PROGRAMFILES', line, re.I),
                f'Unexpected ProgramFiles override found: {line}',
            )
        # In SEC_MAIN and Uninstall, $INSTDIR is never reassigned after the user chooses it.
        sec_idx = uncommented.index('Section "安装主程序" SEC_MAIN')
        sections_body = '\n'.join(uncommented[sec_idx:])
        self.assertNotIn('StrCpy $INSTDIR', sections_body)

        # 2.0 identity, port 8766, distinct shortcuts, and no elevated LocalAppData DB creation.
        self.assertIn('!define APP_ID "ChangfuliElevatorDesktop"', uncommented)
        self.assertIn('!define APP_VERSION "2.0.1"', uncommented)
        self.assertIn('!define FIREWALL_RULE "ChangfuliElevatorDesktop.PrivateLAN.8766"', uncommented)
        self.assertIn('localport=8766 program="$INSTDIR\\runtime\\pythonw.exe"', text)
        self.assertIn('Icon "${ICON_FILE}"', uncommented)
        self.assertNotIn('windows-app.ico', text)
        self.assertIn('CreateShortcut "$DESKTOP\\${APP_NAME}.lnk"', text)
        for shortcut in (
            '启动电梯管理系统 2.0.lnk',
            '停止电梯管理系统 2.0.lnk',
            '打开数据目录 2.0.lnk',
            '卸载电梯管理系统 2.0.lnk',
        ):
            self.assertIn(shortcut, text)
        for old_shortcut in (
            '启动电梯管理系统.lnk',
            '停止电梯管理系统.lnk',
            '打开数据目录.lnk',
            '卸载电梯管理系统.lnk',
        ):
            self.assertNotIn(old_shortcut, text)
        self.assertNotIn('CreateDirectory "$LOCALAPPDATA', text)
        self.assertNotIn('CreateDirectory "$APPDATA', text)
        self.assertNotIn('elevator.db', text)

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
        self.assertIn('Call ValidateInstDir\n  InitPluginsDir', text)
        self.assertNotIn(' /T /C', text)
        stage = self.root / 'payload'; stage.mkdir(); (stage / 'fixture.txt').write_text('fixture')
        target = self.root / 'fixture-installer.exe'
        subprocess.run([shutil.which('makensis'), '-V2', f'-DSTAGE_DIR={stage}', f'-DOUT_FILE={target}', str(source)], check=True)
        self.assertEqual(target.read_bytes()[:2], b'MZ')


if __name__ == '__main__':
    unittest.main()

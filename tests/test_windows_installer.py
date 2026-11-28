"""Build-input, staging, 2.0 identity, directory selection and NSIS compilation checks; no live business data is used."""
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

from PIL import Image, ImageChops, ImageStat

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
            builder.stage_application(runtime, self.root, output, '2.0.3')
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
            stage = builder.stage_application(python_zip, self.root, output, '2.0.3')
            self.assertEqual((stage / 'runtime/python312._pth').read_text(), builder.PTH_CONTENT)
            self.assertFalse((stage / 'data').exists())
            self.assertFalse((stage / 'seed').exists())
            self.assertFalse((stage / 'seed/official-ledger.xlsx').exists())
            self.assertFalse((stage / 'backend/__pycache__').exists())
            self.assertFalse((stage / 'tests').exists())
            self.assertTrue((stage / builder.APP_ICON_ICO).is_file())
            self.assertTrue((stage / builder.APP_ICON_PNG).is_file())
            manifest = json.loads((stage / 'BUILD-MANIFEST.json').read_text())
            self.assertEqual(manifest['product'], 'ChangfuliElevatorDesktop')
            self.assertEqual(manifest['version'], '2.0.3')
            self.assertNotIn('seed/official-ledger.xlsx', manifest['files'])
            for name, digest in manifest['files'].items():
                self.assertEqual(builder.sha256(stage / name), digest)
            self.assertTrue((stage / 'licenses/demo-1.0.dist-info/LICENSE').is_file())
            self.assertFalse(list(stage.rglob('*.xlsx')))
            # Even if source/seed/official-ledger.xlsx exists, default stage never copies it without --seed-ledger.
            unrequested_seed = source / 'seed/official-ledger.xlsx'
            unrequested_seed.parent.mkdir(parents=True, exist_ok=True)
            unrequested_seed.write_bytes(b'do not stage by default')
            stage = builder.stage_application(python_zip, self.root, output, '2.0.3')
            self.assertFalse((stage / 'seed').exists())
            self.assertFalse(list(stage.rglob('*.xlsx')))
            # Unrequested .xlsx inside a copied directory tree must also be rejected on default empty build.
            stray_xlsx = source / 'frontend/dist/unwanted.xlsx'
            stray_xlsx.write_bytes(b'unwanted')
            try:
                with self.assertRaisesRegex(ValueError, 'unwanted.xlsx'):
                    builder.stage_application(python_zip, self.root, output, '2.0.3')
            finally:
                stray_xlsx.unlink()
            fixture = ROOT / 'tests/fixtures/synthetic-ledger-fixture.xlsx'
            stage = builder.stage_application(python_zip, self.root, output, '2.0.3', seed_ledger=fixture)
            manifest = json.loads((stage / 'BUILD-MANIFEST.json').read_text())
            self.assertEqual(manifest['files']['seed/official-ledger.xlsx'], builder.sha256(fixture))
            self.assertEqual((stage / 'seed/official-ledger.xlsx').read_bytes(), fixture.read_bytes())
            # Subsequent default empty stage must wipe any prior stage/seed/official-ledger.xlsx.
            stage = builder.stage_application(python_zip, self.root, output, '2.0.3')
            self.assertFalse((stage / 'seed').exists())
            self.assertFalse(list(stage.rglob('*.xlsx')))
            (stage / 'BUILD-MANIFEST.json').unlink()
            with self.assertRaises(ValueError):
                builder.stage_application(python_zip, self.root, output, '2.0.3')
            self.assertTrue((stage / 'backend/main.py').is_file())

    def test_brand_icons_are_rebuilt_from_first_version_white_27_ico_and_versions_are_2_0_3(self):
        source_ico_path = ROOT / 'scripts/windows-app.ico'
        ico_path = ROOT / 'scripts/desktop-app-2.0.ico'
        png_path = ROOT / 'scripts/desktop-app-2.0.png'
        web_png_path = ROOT / 'frontend/src/assets/desktop-app-2.0.png'
        self.assertTrue(source_ico_path.is_file())
        self.assertTrue(ico_path.is_file())
        self.assertTrue(png_path.is_file())
        self.assertTrue(web_png_path.is_file())

        def read_ico_frames(path: Path):
            raw = path.read_bytes()
            reserved, ico_type, count = struct.unpack_from('<HHH', raw, 0)
            self.assertEqual((reserved, ico_type), (0, 1))
            frames = {}
            for idx in range(count):
                w, h, _, _, _, _, size, offset = struct.unpack_from('<BBBBHHII', raw, 6 + idx * 16)
                actual_w = 256 if w == 0 else w
                actual_h = 256 if h == 0 else h
                self.assertEqual(actual_w, actual_h)
                frames[actual_w] = Image.open(io.BytesIO(raw[offset:offset + size])).convert('RGBA')
            return frames

        expected_sizes = {(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}
        with Image.open(ico_path) as ico:
            self.assertEqual(ico.format, 'ICO')
            self.assertTrue(expected_sizes.issubset(ico.info.get('sizes', set())))

        orig_frames = read_ico_frames(source_ico_path)
        new_frames = read_ico_frames(ico_path)
        self.assertEqual(set(new_frames), {16, 24, 32, 48, 64, 128, 256})

        # Rendered 256px and 64px frames visually match the original white-27 mark, not emblem or cobalt tile.
        for sz in (64, 256):
            diff = ImageChops.difference(new_frames[sz], orig_frames[sz])
            for channel_mean in ImageStat.Stat(diff).mean:
                self.assertLess(channel_mean, 1.0)
        # 16px frame stays faithful to the original white-27 mark while maintaining sharp ink/bar contrast.
        diff_16 = ImageChops.difference(new_frames[16], orig_frames[16])
        for channel_mean in ImageStat.Stat(diff_16).mean:
            self.assertLess(channel_mean, 12.0)
        frame16 = new_frames[16]
        # White card background, dark "27" ink, and cobalt right vertical bar are all distinct at 16px.
        self.assertTrue(any(frame16.getpixel((x, 2))[:3] == (255, 255, 255) for x in range(4, 12)))
        min_luma_16 = min(sum(frame16.getpixel((x, y))[:3]) / 3 for y in range(4, 12) for x in range(2, 11))
        self.assertLess(min_luma_16, 50)
        max_blue_excess_16 = max(frame16.getpixel((x, 8))[2] - frame16.getpixel((x, 8))[0] for x in range(12, 16))
        self.assertGreater(max_blue_excess_16, 60)

        for icon_file in (png_path, web_png_path):
            with Image.open(icon_file) as png:
                self.assertEqual(png.format, 'PNG')
                self.assertEqual(png.mode, 'RGBA')
                self.assertGreaterEqual(png.size[0], 256)
                self.assertEqual(png.size[0], png.size[1])
                rendered = png.convert('RGBA').resize((256, 256), Image.Resampling.LANCZOS)
                diff = ImageChops.difference(rendered, orig_frames[256])
                for channel_mean in ImageStat.Stat(diff).mean:
                    self.assertLess(channel_mean, 1.0)
                # Corners are transparent; card background is pure white (not travertine stone or flat cobalt #435ddd).
                self.assertEqual(rendered.getpixel((0, 0))[3], 0)
                self.assertEqual(rendered.getpixel((128, 24)), (255, 255, 255, 255))
                self.assertNotEqual(rendered.getpixel((128, 24))[:3], (67, 93, 221))

        index_html = (ROOT / 'frontend/index.html').read_text(encoding='utf-8')
        self.assertIn('/src/assets/desktop-app-2.0.png', index_html)
        self.assertIn('<title>昌福里社区电梯管理系统</title>', index_html)
        self.assertNotIn('2.0.2', index_html)

        package_json = json.loads((ROOT / 'frontend/package.json').read_text(encoding='utf-8'))
        self.assertEqual(package_json['version'], '2.0.3')

        lock = json.loads((ROOT / 'frontend/package-lock.json').read_text(encoding='utf-8'))
        self.assertEqual(lock['version'], package_json['version'])
        self.assertEqual(lock['packages']['']['version'], package_json['version'])

        app_vue = (ROOT / 'frontend/src/App.vue').read_text(encoding='utf-8')
        self.assertIn("./assets/elevator-lobby.jpg", app_vue)
        self.assertNotIn('architecture.svg', app_vue)
        self.assertIn('打开即可使用 · 无需登录 · 2.0.3', app_vue)
        self.assertIn('本机与局域网 · 版本 2.0.3', app_vue)
        self.assertIn('一梯一档 · 2.0.3', app_vue)
        self.assertNotIn('2.0.2', app_vue)

        self.assertIn('2.0.3', (ROOT / 'scripts/run.py').read_text(encoding='utf-8'))
        self.assertIn('2.0.3', (ROOT / 'scripts/package_release.py').read_text(encoding='utf-8'))

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

        # 2.x identity, port 8766, clean display names, and no elevated LocalAppData DB creation.
        self.assertIn('!define APP_ID "ChangfuliElevatorDesktop"', uncommented)
        self.assertIn('!define APP_VERSION "2.0.3"', uncommented)
        self.assertIn('!define FIREWALL_RULE "ChangfuliElevatorDesktop.PrivateLAN.8766"', uncommented)
        self.assertIn('localport=8766 program="$INSTDIR\\runtime\\pythonw.exe"', text)
        self.assertIn('Icon "${ICON_FILE}"', uncommented)
        self.assertNotIn('windows-app.ico', text)
        self.assertIn('!define APP_NAME "昌福里社区电梯管理系统"', uncommented)
        self.assertIn('!define MENU_NAME "昌福里社区电梯管理系统"', uncommented)
        for line in uncommented:
            if line.startswith(('!define MUI_', 'DetailPrint ', 'MessageBox ')):
                self.assertNotIn('2.0', line)
        self.assertNotIn('CreateDirectory "$LOCALAPPDATA', text)
        self.assertNotIn('CreateDirectory "$APPDATA', text)
        self.assertNotIn('elevator.db', text)

    def test_nonempty_install_directory_requires_registered_desktop_installation(self):
        text = (ROOT / 'scripts/windows_installer.nsi').read_text(encoding='utf-8')
        guard = text.split('Function ${PREFIX}CheckInstDirSafe\n', 1)[1].split('FunctionEnd', 1)[0]
        missing, existing = guard.split('IntOp $1 $0 & 0x400', 1)
        self.assertIn('${If} $1 == 2\n    ${OrIf} $1 == 3\n      Push "ok"', missing)
        ordinary_dir, ownership = existing.split('shlwapi::PathIsDirectoryEmptyW', 1)
        self.assertIn('IntOp $1 $0 & 0x10', ordinary_dir)
        self.assertNotIn('Push "ok"', ordinary_dir)
        empty, registered = ownership.split('ReadRegStr $0 HKLM "${UNINSTALL_KEY}" "InstallLocation"', 1)
        self.assertIn('${If} $0 != 0\n    Push "ok"\n    Return', empty)
        self.assertIn(
            '${If} $0 == "$INSTDIR"\n'
            '  ${AndIf} ${FileExists} "$INSTDIR\\${ICON_FILE}"\n'
            '  ${AndIf} ${FileExists} "$INSTDIR\\Uninstall.exe"\n'
            '    Push "ok"\n    Return', registered)
        self.assertIn('请选择空的专用文件夹', registered.split('${EndIf}', 1)[1])

        install = text.split('Section "安装主程序" SEC_MAIN', 1)[1].split('SectionEnd', 1)[0]
        self.assertLess(install.index('Call ValidateInstDir'), install.index('!insertmacro RemoveProgramFiles'))
        validate = text.split('Function ${PREFIX}ValidateInstDir\n', 1)[1].split('FunctionEnd', 1)[0]
        self.assertIn('Call ${PREFIX}CheckInstDirSafe', validate)
        self.assertIn('${If} $0 != "ok"', validate)
        self.assertIn('Abort', validate)

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
    def test_compiled_shortcut_paths_and_upgrade_cleanup_order(self):
        (self.root / 'fixture.txt').touch()
        charset = ['-OUTPUTCHARSET', 'UTF8'] if sys.platform == 'win32' else []
        script = subprocess.check_output([
            'makensis', '-PPO', *charset, f'-DSTAGE_DIR={self.root}',
            f'-DOUT_FILE={self.root}/fixture.exe', str(ROOT / 'scripts/windows_installer.nsi'),
        ], encoding='utf-8-sig')
        self.assertIn('VIProductVersion "2.0.3.0"', script)
        install = script.split('Section "安装主程序" SEC_MAIN', 1)[1].split('SectionEnd', 1)[0]
        uninstall = script.split('Section "Uninstall"', 1)[1].split('SectionEnd', 1)[0]
        before_create = install[:install.index('CreateShortcut ')]
        product = '昌福里社区电梯管理系统'
        for suffix in ('', ' 2.0'):
            menu = rf'$SMPROGRAMS\{product}{suffix}'
            paths = [rf'$DESKTOP\{product}{suffix}.lnk']
            paths += [rf'{menu}\{action}{suffix}.lnk' for action in
                      ('启动电梯管理系统', '停止电梯管理系统', '打开数据目录', '卸载电梯管理系统')]
            for section in (before_create, uninstall):
                remove_folder = section.index(f'RMDir "{menu}"')
                for path in paths:
                    self.assertIn(f'Delete "{path}"', section[:remove_folder])
            if not suffix:
                self.assertCountEqual(re.findall(r'^CreateShortcut "([^"]+)"', install, re.M), paths)

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

        # Also run default build_windows_installer.py CLI flow without --seed-ledger and verify empty stage + 2.0.3 exe.
        project, output = self.root / 'default-project', self.root / 'default-output'
        project.mkdir(); output.mkdir()
        for rel, content in {
            'requirements.lock.txt': 'demo==1.0\n',
            'backend/__init__.py': '',
            'backend/main.py': 'VALUE = 1\n',
            'scripts/windows_launcher.py': 'pass\n',
            'frontend/dist/index.html': '<!doctype html><title>昌福里社区电梯管理系统</title>',
            'docs/WINDOWS_INSTALLER.md': 'install docs',
            'USER_GUIDE.md': 'user guide',
        }.items():
            dst = project / rel; dst.parent.mkdir(parents=True, exist_ok=True); dst.write_text(content, encoding='utf-8')
        shutil.copyfile(ROOT / f'scripts/{builder.APP_ICON_ICO}', project / f'scripts/{builder.APP_ICON_ICO}')
        shutil.copyfile(ROOT / f'scripts/{builder.APP_ICON_PNG}', project / f'scripts/{builder.APP_ICON_PNG}')
        shutil.copyfile(ROOT / 'scripts/windows_installer.nsi', project / 'scripts/windows_installer.nsi')
        python_zip = self.root / 'python-embed.zip'
        with ZipFile(python_zip, 'w') as archive:
            for name in ('python.exe', 'pythonw.exe', 'python312.dll', 'python312.zip', 'python312._pth', 'LICENSE.txt'):
                archive.writestr(name, 'runtime fixture')
        self.wheel()
        real_run = subprocess.run

        def run_pip_or_makensis(arguments, **kwargs):
            if len(arguments) >= 3 and arguments[1:3] == ['-m', 'pip']:
                packages = Path(arguments[arguments.index('--target') + 1])
                info = packages / 'demo-1.0.dist-info'; info.mkdir(parents=True)
                (info / 'METADATA').write_text('Name: demo\nVersion: 1.0\n', encoding='utf-8')
                (info / 'LICENSE').write_text('fixture license', encoding='utf-8')
                (packages / 'demo.py').write_text('VALUE = 1\n', encoding='utf-8')
                return None
            return real_run(arguments, **kwargs)

        argv = [
            'build_windows_installer.py',
            '--python-zip', str(python_zip),
            '--wheelhouse', str(self.root),
            '--output-dir', str(output),
        ]
        with patch.object(builder, 'ROOT', project), \
                patch.object(builder, 'PYTHON_SHA256', builder.sha256(python_zip)), \
                patch.object(builder.subprocess, 'run', side_effect=run_pip_or_makensis), \
                patch.object(sys, 'argv', argv):
            builder.main()
        built_exe = output / 'ChangfuliElevatorDesktop-Setup-2.0.3-x64.exe'
        self.assertTrue(built_exe.is_file())
        self.assertEqual(built_exe.read_bytes()[:2], b'MZ')
        self.assertTrue(built_exe.with_suffix('.exe.sha256').is_file())
        staged = output / 'stage'
        self.assertFalse((staged / 'seed').exists())
        self.assertFalse((staged / 'seed/official-ledger.xlsx').exists())
        self.assertEqual(list(staged.rglob('*.xlsx')), [])
        manifest = json.loads((staged / 'BUILD-MANIFEST.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['version'], '2.0.3')
        self.assertNotIn('seed/official-ledger.xlsx', manifest['files'])


if __name__ == '__main__':
    unittest.main()
